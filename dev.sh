#!/usr/bin/env bash
set -e

docker compose up -d
echo "Waiting for app to be healthy..."
until curl -sf localhost:8000/health > /dev/null; do sleep 1; done
echo "Backend ready. Starting Telegram bot..."
REDIS_HOST=localhost REDIS_PORT=16379 POSTGRES_HOST=localhost POSTGRES_PORT=15432 uv run python -m app.telegram.bot
