@echo off
REM Starts the Kronos forecast service on this PC (http://127.0.0.1:8000). Needs Python 3.11 or 3.12.
cd /d "%~dp0..\.."
if not exist .venv ( py -3 -m venv .venv )
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r forecast_service\requirements.txt
if "%KRONOS_SECRET%"=="" set /p KRONOS_SECRET=Choose a secret key (same one goes into Vercel): 
uvicorn forecast_service.app:app --host 127.0.0.1 --port 8000
pause
