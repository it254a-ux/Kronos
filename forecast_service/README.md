# Forecast service (added on top of Kronos; `model/` is unchanged)

`POST /forecast` takes OHLC candles and returns several forecast paths from the real Kronos model,
the median and 10/90% close bands, and (if `levels` is sent) the share of paths that hit TP before SL.

```json
{ "candles":[{"t":1700000000,"o":4100,"h":4101,"l":4099,"c":4100.5}, "... 64-512 of them ..."],
  "pred_len":60, "paths":10, "levels":{"side":"sell","tp":4121,"sl":4127} }
```

Env vars: `KRONOS_SECRET` (callers must send it as `X-API-Key`), `KRONOS_MODEL` (default `NeoQuasar/Kronos-small`).

## Deploy on a Hugging Face Space (Docker)
1. New Space -> SDK: Docker -> blank. Add this fork as the Space's repo (or push this branch to the Space).
2. Settings -> Variables and secrets -> add secret `KRONOS_SECRET` (any long random string).
3. Build with `forecast_service/Dockerfile` (in the Space README front matter set `app_port: 7860`).
4. Open `https://<space>.hf.space/health`; the first `/forecast` call downloads the weights.

Offline logic test (no weights): `PYTHONPATH=. python forecast_service/test_logic.py`
Probabilities are model samples, not guarantees. Test on a demo account first.
