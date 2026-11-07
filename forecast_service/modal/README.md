# Run the forecast service on Modal (no laptop needed)

Modal's free Starter plan includes $30 of compute a month and bills per second (nothing while asleep).
The service sleeps when unused, so the first forecast after a quiet spell is slower while it wakes up.

1. Get the files (Windows, from a Command Prompt):
   `curl -L -o C:\kronos\Kronos-forecast-service\forecast_service\modal_app.py https://raw.githubusercontent.com/it254a-ux/Kronos/forecast-service/forecast_service/modal_app.py`
   `curl -L -o C:\kronos\Kronos-forecast-service\forecast_service\app.py https://raw.githubusercontent.com/it254a-ux/Kronos/forecast-service/forecast_service/app.py`
   `curl -L -o C:\kronos\Kronos-forecast-service\forecast_service\local\deploy_modal.bat https://raw.githubusercontent.com/it254a-ux/Kronos/forecast-service/forecast_service/local/deploy_modal.bat`
2. Run `cd /d C:\kronos\Kronos-forecast-service\forecast_service\local && deploy_modal.bat` and follow the three steps it prints.
3. Copy the web address ending in `.modal.run`. In Vercel set `KRONOS_URL` to it (no `/` at the end), then redeploy.
4. Check `https://<that address>/health` in the browser.

Other computers: `pip install modal`, `modal setup`, `modal secret create kronos-secret KRONOS_SECRET=...`,
`modal deploy forecast_service/modal_app.py` (run from the repo root).
