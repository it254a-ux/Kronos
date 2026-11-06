"""Forecast API around the unchanged Kronos model (../model).

POST /jobs       -> start a forecast (returns {"job": id} at once, or 429 if one is already running)
GET  /jobs/{id}  -> {"status": "running" | "done" | "error", "elapsed": s, "result": {...}}
POST /forecast   -> the same forecast in one call (waits for the answer; handy for tests)
GET  /health     -> liveness check.
A forecast gives several paths for OHLC candles, plus the share of paths that reach a take profit before a stop loss.
Env: KRONOS_MODEL (default NeoQuasar/Kronos-small), KRONOS_SECRET (optional key
checked against the X-API-Key header), KRONOS_DEVICE (default cpu).
"""
import os
import sys
import re
import threading
import time
import uuid
from typing import List, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODEL_ID = os.getenv("KRONOS_MODEL", "NeoQuasar/Kronos-small")
TOKENIZER_ID = os.getenv("KRONOS_TOKENIZER", "NeoQuasar/Kronos-Tokenizer-base")
DEVICE = os.getenv("KRONOS_DEVICE", "cpu")
SECRET = os.getenv("KRONOS_SECRET", "")
MAX_CONTEXT = 2048 if "mini" in MODEL_ID else 512
# fewer candles of history = a much faster forecast on a normal laptop (attention cost grows with the square)
LOOKBACK = min(int(os.getenv("KRONOS_LOOKBACK", "256")), MAX_CONTEXT)

app = FastAPI(title="Kronos forecast service")
_predictor = None
_lock = threading.Lock()  # guards loading the model
# Kronos keeps working data inside the model (its rotary-position cache), so two forecasts running at the
# same time overwrite each other and crash with "size of tensor a must match tensor b". One at a time only.
_infer_lock = threading.Lock()


def get_predictor():
    global _predictor
    with _lock:
        if _predictor is None:
            from model import Kronos, KronosPredictor, KronosTokenizer

            tokenizer = KronosTokenizer.from_pretrained(TOKENIZER_ID)
            model = Kronos.from_pretrained(MODEL_ID)
            _predictor = KronosPredictor(model, tokenizer, device=DEVICE, max_context=MAX_CONTEXT)
        return _predictor


class Candle(BaseModel):
    t: int = Field(..., description="Candle open time, epoch seconds")
    o: float
    h: float
    l: float
    c: float


class Levels(BaseModel):
    side: str = Field(..., pattern="^(buy|sell)$")
    entry: Optional[float] = None
    tp: float
    sl: float


class ForecastRequest(BaseModel):
    candles: List[Candle]
    pred_len: int = Field(60, ge=1, le=120)
    paths: int = Field(10, ge=1, le=30)
    temperature: float = Field(1.0, gt=0, le=2.0)
    top_p: float = Field(0.9, gt=0, le=1.0)
    levels: Optional[Levels] = None


def tp_before_sl(paths, levels: Levels):
    """Share of paths hitting TP first / SL first / neither. If one candle touches
    both, SL is counted first (the cautious assumption)."""
    tp_first = sl_first = 0
    for p in paths:
        outcome = None
        for k in p:
            if levels.side == "buy":
                hit_sl, hit_tp = k["l"] <= levels.sl, k["h"] >= levels.tp
            else:
                hit_sl, hit_tp = k["h"] >= levels.sl, k["l"] <= levels.tp
            if hit_sl:
                outcome = "sl"
                break
            if hit_tp:
                outcome = "tp"
                break
        if outcome == "tp":
            tp_first += 1
        elif outcome == "sl":
            sl_first += 1
    n = len(paths)
    return {
        "tp_first": tp_first / n,
        "sl_first": sl_first / n,
        "neither": (n - tp_first - sl_first) / n,
    }


def _preload():
    """Load the model in the background at start-up so the first forecast does not wait for it."""
    try:
        get_predictor()
        print("Kronos model loaded and ready.", flush=True)
    except Exception as exc:  # the first forecast will try again and report the error
        print(f"Kronos preload failed: {exc}", flush=True)


if os.getenv("KRONOS_PRELOAD", "1") == "1":
    threading.Thread(target=_preload, daemon=True).start()


@app.get("/health")
def health():
    return {"ok": True, "model": MODEL_ID, "loaded": _predictor is not None}


def _check_key(x_api_key):
    if SECRET and x_api_key != SECRET:
        raise HTTPException(status_code=401, detail="bad api key")


def _prepare(req: ForecastRequest):
    """Checks the candles and builds what the model needs. Raises 422 for bad input."""
    if len(req.candles) < 64:
        raise HTTPException(status_code=422, detail="send at least 64 candles")
    df = pd.DataFrame([c.model_dump() for c in req.candles]).sort_values("t").drop_duplicates("t")
    df = df.tail(LOOKBACK).reset_index(drop=True)
    step = int(np.median(np.diff(df["t"].values)))
    if step <= 0:
        raise HTTPException(status_code=422, detail="candle times must increase")
    x_ts = pd.Series(pd.to_datetime(df["t"], unit="s"))
    last_t = int(df["t"].iloc[-1])
    future_t = [last_t + step * (i + 1) for i in range(req.pred_len)]
    y_ts = pd.Series(pd.to_datetime(future_t, unit="s"))
    frame = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close"})[["open", "high", "low", "close"]]
    return df, frame, x_ts, y_ts, future_t, step


def _compute(req: ForecastRequest, prepared):
    """Runs the model. The caller must hold _infer_lock."""
    df, frame, x_ts, y_ts, future_t, step = prepared
    predictor = get_predictor()
    outs = predictor.predict_batch(
        df_list=[frame] * req.paths,
        x_timestamp_list=[x_ts] * req.paths,
        y_timestamp_list=[y_ts] * req.paths,
        pred_len=req.pred_len,
        T=req.temperature,
        top_p=req.top_p,
        sample_count=1,
        verbose=False,
    )
    paths = []
    for out in outs:
        o = out.reset_index(drop=True)
        paths.append(
            [
                {"t": future_t[i], "o": float(o.open[i]), "h": float(max(o.high[i], o.open[i], o.close[i])),
                 "l": float(min(o.low[i], o.open[i], o.close[i])), "c": float(o.close[i])}
                for i in range(req.pred_len)
            ]
        )
    closes = np.array([[k["c"] for k in p] for p in paths])
    last_close = float(df["c"].iloc[-1])
    result = {
        "step": step,
        "last_close": last_close,
        "paths": paths,
        "median_close": np.median(closes, axis=0).tolist(),
        "p10_close": np.percentile(closes, 10, axis=0).tolist(),
        "p90_close": np.percentile(closes, 90, axis=0).tolist(),
        "up_share": float((closes[:, -1] > last_close).mean()),
        "note": "Probabilities are model samples, not guarantees.",
    }
    if req.levels:
        result["levels"] = tp_before_sl(paths, req.levels)
    return result


@app.post("/forecast")
def forecast(req: ForecastRequest, x_api_key: Optional[str] = Header(default=None)):
    _check_key(x_api_key)
    prepared = _prepare(req)
    if not _infer_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="busy: still working on another forecast")
    try:
        return _compute(req, prepared)
    finally:
        _infer_lock.release()


# ---- jobs: start now, collect the answer later (a slow laptop may need minutes, and callers should not wait that long)
_jobs = {}
_JOB_KEEP_SECONDS = 15 * 60
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")


def _run_job(job_id: str, req: ForecastRequest, prepared):
    try:
        result = _compute(req, prepared)
        _jobs[job_id].update(status="done", result=result, finished=time.time())
    except Exception as exc:  # shown to the person as a plain message; details stay in this window
        print(f"Forecast job failed: {exc!r}", flush=True)
        _jobs[job_id].update(status="error", error="The model hit a problem. Please try again.", finished=time.time())
    finally:
        _infer_lock.release()


@app.post("/jobs")
def start_job(req: ForecastRequest, x_api_key: Optional[str] = Header(default=None)):
    _check_key(x_api_key)
    prepared = _prepare(req)
    now = time.time()
    for old in [k for k, v in _jobs.items() if now - v["started"] > _JOB_KEEP_SECONDS]:
        _jobs.pop(old, None)
    if not _infer_lock.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="busy: still working on another forecast")
    job_id = uuid.uuid4().hex
    _jobs[job_id] = {"status": "running", "started": now}
    threading.Thread(target=_run_job, args=(job_id, req, prepared), daemon=True).start()
    return {"job": job_id}


@app.get("/jobs/{job_id}")
def job_status(job_id: str, x_api_key: Optional[str] = Header(default=None)):
    _check_key(x_api_key)
    job = _jobs.get(job_id) if _JOB_ID.match(job_id) else None
    if not job:
        raise HTTPException(status_code=404, detail="unknown job")
    body = {"status": job["status"], "elapsed": round((job.get("finished") or time.time()) - job["started"], 1)}
    if job["status"] == "done":
        body["result"] = job["result"]
    if job["status"] == "error":
        body["error"] = job["error"]
    return body
