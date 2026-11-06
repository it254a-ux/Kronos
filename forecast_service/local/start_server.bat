@echo off
REM Starts the forecast service again (no installing). Use this every day after the first setup.
cd /d "%~dp0..\.."
call .venv\Scripts\activate
if "%KRONOS_SECRET%"=="" set /p KRONOS_SECRET=Secret key (same one as in Vercel): 
uvicorn forecast_service.app:app --host 127.0.0.1 --port 8000
pause
