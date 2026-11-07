@echo off
REM Puts the forecast service on Modal (so no laptop has to stay on). Run it from the project folder; follow the prompts.
cd /d "%~dp0..\.."
call .venv\Scripts\activate
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
pip install --upgrade modal
echo.
echo STEP 1 of 3: a browser window opens - log in to Modal (use "Sign in with GitHub") and approve.
modal setup
echo.
echo STEP 2 of 3: the secret key must be the SAME one you put in Vercel (KRONOS_SECRET).
set /p KEY=Secret key: 
modal secret create kronos-secret KRONOS_SECRET=%KEY% --force
echo.
echo STEP 3 of 3: building and publishing (the first time takes about 5-10 minutes).
modal deploy forecast_service\modal_app.py
echo.
echo Look above for a web address ending in .modal.run  - that is your new KRONOS_URL.
pause
