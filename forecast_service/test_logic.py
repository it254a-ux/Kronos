"""Offline check of the endpoint logic with a stand-in predictor (no weights needed).
Run from the repo root:  PYTHONPATH=. python forecast_service/test_logic.py"""
import os, threading, time
os.environ["KRONOS_PRELOAD"] = "0"
import numpy as np, pandas as pd
from fastapi.testclient import TestClient
import forecast_service.app as svc

class Fake:
    def predict_batch(self, df_list, x_timestamp_list, y_timestamp_list, pred_len, **kw):
        out = []
        for i, d in enumerate(df_list):
            r = np.random.default_rng(i); c = d.close.iloc[-1] + np.cumsum(r.normal(0, 0.5, pred_len))
            out.append(pd.DataFrame({"open": c, "high": c + 0.3, "low": c - 0.3, "close": c}))
        return out

svc._predictor = Fake()
t0 = 1_700_000_000
cs = [{"t": t0 + 300 * i, "o": 4100 + i * .1, "h": 4101 + i * .1, "l": 4099 + i * .1, "c": 4100.5 + i * .1} for i in range(420)]
c = TestClient(svc.app)
r = c.post("/forecast", json={"candles": cs, "pred_len": 30, "paths": 8,
           "levels": {"side": "sell", "tp": cs[-1]["c"] - 3, "sl": cs[-1]["c"] + 3}})
assert r.status_code == 200, r.text
j = r.json(); assert len(j["paths"]) == 8 and len(j["paths"][0]) == 30 and j["step"] == 300
assert abs(sum(j["levels"].values()) - 1) < 1e-9
assert c.post("/forecast", json={"candles": cs[:10]}).status_code == 422

# two forecasts at once: the second must be told "busy" (429), never run in parallel
class Slow(Fake):
    def predict_batch(self, *a, **k):
        time.sleep(0.6)
        return super().predict_batch(*a, **k)

svc._predictor = Slow()
codes = []
def go(): codes.append(c.post("/forecast", json={"candles": cs, "pred_len": 5, "paths": 2}).status_code)
th = [threading.Thread(target=go) for _ in range(2)]
[x.start() for x in th]; [x.join() for x in th]
assert sorted(codes) == [200, 429], codes
assert c.post("/forecast", json={"candles": cs, "pred_len": 5, "paths": 2}).status_code == 200  # free again afterwards

# jobs: start now, collect later; one at a time
svc._predictor = Slow()
body = {"candles": cs, "pred_len": 5, "paths": 2, "levels": {"side": "sell", "tp": cs[-1]["c"] - 3, "sl": cs[-1]["c"] + 3}}
r = c.post("/jobs", json=body); assert r.status_code == 200, r.text
job = r.json()["job"]
assert c.post("/jobs", json=body).status_code == 429          # still running
assert c.get(f"/jobs/{job}").json()["status"] == "running"
for _ in range(50):
    st = c.get(f"/jobs/{job}").json()
    if st["status"] != "running": break
    time.sleep(0.1)
assert st["status"] == "done" and len(st["result"]["paths"]) == 2 and "levels" in st["result"], st
assert c.post("/jobs", json=body).status_code == 200           # free again once finished
time.sleep(1)
assert c.get("/jobs/not-a-real-id").status_code == 404
assert c.get("/jobs/" + "0" * 32).status_code == 404
svc.SECRET = "k"
assert c.post("/jobs", json=body).status_code == 401
assert c.get(f"/jobs/{job}").status_code == 401
assert c.get(f"/jobs/{job}", headers={"X-API-Key": "k"}).status_code == 200
svc.SECRET = ""

# a model that crashes gives the person a plain message, not the details
class Boom:
    def predict_batch(self, *a, **k): raise RuntimeError("secret internal detail")
svc._predictor = Boom()
job = c.post("/jobs", json=body).json()["job"]
for _ in range(50):
    st = c.get(f"/jobs/{job}").json()
    if st["status"] != "running": break
    time.sleep(0.1)
assert st["status"] == "error" and "secret" not in str(st), st
print("ok", j["levels"], j["up_share"], codes)
