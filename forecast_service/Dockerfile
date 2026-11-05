# Build from the repo root:  docker build -f forecast_service/Dockerfile -t kronos-forecast .
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 HF_HOME=/tmp/hf
WORKDIR /app
COPY forecast_service/requirements.txt /tmp/req.txt
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r /tmp/req.txt
COPY model ./model
COPY forecast_service ./forecast_service
EXPOSE 7860
CMD ["uvicorn", "forecast_service.app:app", "--host", "0.0.0.0", "--port", "7860"]
