# Production Deploy Notes

Use `deploy/docker-compose.prod.yml` on the VPS. It builds from
`Dockerfile.playwright` so the runtime has the browser dependencies needed for
TradingView, then overrides the container command back to `uvicorn`.

## Secrets

Create `deploy/.env.production` on the VPS and keep it out of git.

```bash
chmod 600 deploy/.env.production
```

Minimum variables:

```dotenv
APP_ENV=production
APP_ENCRYPTION_KEY=...
POSTGRES_DB=earning_edge
POSTGRES_USER=earning_edge
POSTGRES_PASSWORD=...
REDIS_HOST=redis
REDIS_PORT=6379
TELEGRAM_BOT_TOKEN=...
TRADINGVIEW_EMAIL=...
TRADINGVIEW_PASSWORD=...
TRADINGVIEW_HEADLESS=true
TRADINGVIEW_TIMEOUT_MS=30000
FINNHUB_API_KEY=
```

Add any production-only overrides here rather than editing the compose file.

## Bring Up

```bash
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production up -d --build
docker compose -f deploy/docker-compose.prod.yml logs -f app
```

The compose file keeps these paths persistent across restarts:

- `../var/tradingview` for Playwright auth state
- `../var/runs` for JSON run archives

## Hardening Notes

- TradingView runs headless in production via `TRADINGVIEW_HEADLESS=true`.
- Docker log rotation is enabled with `max-size=10m` and `max-file=5`.
- Postgres and Redis are internal-only in the prod compose file; do not publish
  those ports unless you also lock them down at the network layer.
- Run `alembic upgrade head` after deploys that carry schema changes.

## Postgres Backup

Store backups outside the container and schedule them from host cron:

```bash
mkdir -p /opt/earning-edge/backups
docker compose -f /opt/earning-edge/deploy/docker-compose.prod.yml \
  --env-file /opt/earning-edge/deploy/.env.production \
  exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" \
  > /opt/earning-edge/backups/earning_edge-$(date +%F).sql
```

Example cron entry:

```cron
15 3 * * * /bin/bash -lc 'cd /opt/earning-edge && docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env.production exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > /opt/earning-edge/backups/earning_edge-$(date +\%F).sql'
```

Prune old dumps with `find /opt/earning-edge/backups -type f -mtime +14 -delete`
or your preferred retention policy.
