"""Forecast API around the unchanged Kronos model (../model).

POST /forecast  -> several forecast paths for OHLC candles, plus the share of
                   paths that reach a take profit before a stop loss.
GET  /health    -> liveness check.
Env: KRONOS_MODEL (default NeoQuasar/Kronos-small), KRONOS_SECRET (optional key
checked against the X-API-Key header), KRONOS_DEVICE (default cpu).
"""
import os
import sys
import threading
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
LOOKBACK = min(400, MAX_CONTEXT)

app = FastAPI(title="Kronos forecast service")
_predictor = None
_lock = threading.Lock()


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


@app.get("/health")
def health():
    return {"ok": True, "model": MODEL_ID, "loaded": _predictor is not None}


@app.post("/forecast")
def forecast(req: ForecastRequest, x_api_key: Optional[str] = Header(default=None)):
    if SECRET and x_api_key != SECRET:
        raise HTTPException(status_code=401, detail="bad api key")
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
    frame = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close"})[
        ["open", "high", "low", "close"]
    ]

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
