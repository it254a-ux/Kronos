"""Runs the Kronos forecast service on Modal (https://modal.com) so no laptop has to stay on.

This wraps the same FastAPI app as everywhere else (forecast_service/app.py): POST /jobs, GET /jobs/{id}, /health.
Deploy from the repo root:  modal deploy forecast_service/modal_app.py
Needs a Modal secret named "kronos-secret" holding KRONOS_SECRET (see forecast_service/modal/README.md).

How it behaves on Modal:
- It sleeps when nobody uses it (Modal bills per second, nothing while asleep), so the first forecast after a quiet
  spell waits for the container and model to start. The weights are baked into the image, so there is no download.
- Exactly one container runs (max_containers=1), because forecasts are kept in that container's memory and the model
  runs one forecast at a time. Several requests can reach it together (polling while it computes).
"""
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
MODEL = "NeoQuasar/Kronos-small"
TOKENIZER = "NeoQuasar/Kronos-Tokenizer-base"


def _download_weights():
    """Runs once while the image is built, so the weights are already on disk when a container starts."""
    from huggingface_hub import snapshot_download

    snapshot_download(MODEL)
    snapshot_download(TOKENIZER)


image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("torch", index_url="https://download.pytorch.org/whl/cpu")
    .pip_install(
        "fastapi>=0.110",
        "pydantic>=2",
        "numpy",
        "pandas==2.2.2",
        "einops==0.8.1",
        "huggingface_hub==0.33.1",
        "safetensors==0.6.2",
        "tqdm==4.67.1",
    )
    .env({"HF_HOME": "/hf"})
    .run_function(_download_weights)
    .env(
        {
            "HF_HUB_OFFLINE": "1",
            "KRONOS_PRELOAD": "1",
            "OMP_NUM_THREADS": "4",
            "MKL_NUM_THREADS": "4",
        }
    )
    .add_local_dir(ROOT / "model", "/root/model", ignore=["**/__pycache__/**"])
    .add_local_dir(ROOT / "forecast_service", "/root/forecast_service", ignore=["**/__pycache__/**", "local/**", "modal/**"])
)

app = modal.App("kronos-forecast", image=image, secrets=[modal.Secret.from_name("kronos-secret")])


@app.function(cpu=4.0, memory=8192, max_containers=1, scaledown_window=180, timeout=3600)
@modal.concurrent(max_inputs=16)
@modal.asgi_app()
def web():
    import sys

    sys.path.insert(0, "/root")
    from forecast_service.app import app as fastapi_app

    return fastapi_app
