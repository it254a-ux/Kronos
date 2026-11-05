# Always-on deploy (VPS + Docker + automatic HTTPS)

Needs: a VPS with 4 GB RAM (Ubuntu 22.04/24.04) and a DNS A record `forecast.<yourdomain>` -> the VPS IP.

```bash
curl -fsSL https://get.docker.com | sh
git clone -b forecast-service https://github.com/it254a-ux/Kronos.git && cd Kronos/forecast_service/deploy
cp .env.example .env && nano .env        # set DOMAIN and KRONOS_SECRET
docker compose up -d --build
curl https://$DOMAIN/health
```
Restarts itself after reboots/crashes. Update: `git pull && docker compose up -d --build`.
Weights are cached in a Docker volume, so they download only once.
