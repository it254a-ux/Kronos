# Free, no card: run on your own PC + a free ngrok tunnel
1. Install Python 3.11 or 3.12 (tick "Add to PATH"). Download this repo (branch `forecast-service`) and unzip.
2. Double-click `forecast_service\local\run_windows.bat`, enter a secret key. First run downloads the model (a few minutes).
3. Free ngrok account -> Dashboard -> Domains -> claim your free static domain. Install ngrok, then in another window:
   `ngrok http --url=YOUR-DOMAIN.ngrok-free.app 8000`
4. Check `https://YOUR-DOMAIN.ngrok-free.app/health`. Works whenever the PC and both windows are on.
