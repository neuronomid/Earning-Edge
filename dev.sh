#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

BOT_PID_FILE="$ROOT_DIR/var/run/dev-bot.pid"
VENV_PYTHON="$ROOT_DIR/.venv/bin/python"
HEALTH_TIMEOUT_SECONDS=60
DOCKER_TIMEOUT_SECONDS=120

docker_is_available() {
  docker info >/dev/null 2>&1
}

docker_desktop_app_path() {
  if [ -d /Applications/Docker.app ]; then
    printf '%s\n' /Applications/Docker.app
    return 0
  fi

  if [ -d "$HOME/Applications/Docker.app" ]; then
    printf '%s\n' "$HOME/Applications/Docker.app"
    return 0
  fi

  return 1
}

wait_for_docker_daemon() {
  local deadline=$((SECONDS + DOCKER_TIMEOUT_SECONDS))

  while [ "$SECONDS" -lt "$deadline" ]; do
    if docker_is_available; then
      return 0
    fi
    sleep 2
  done

  return 1
}

ensure_docker_available() {
  local context="unknown"
  local docker_app=""

  if docker_is_available; then
    return 0
  fi

  context="$(docker context show 2>/dev/null || printf '%s' unknown)"
  if [ "$(uname -s)" = "Darwin" ] && docker_app="$(docker_desktop_app_path)"; then
    echo "Docker daemon is not running. Launching Docker Desktop..."
    open -g -a "$docker_app"
    if wait_for_docker_daemon; then
      return 0
    fi
    echo "Docker Desktop did not become ready within ${DOCKER_TIMEOUT_SECONDS}s." >&2
  fi

  echo "Docker is not available for context '${context}'." >&2
  echo "Start Docker Desktop, Colima, OrbStack, or another Docker-compatible daemon, then rerun ./dev.sh." >&2
  docker context ls >&2 || true
  exit 1
}

wait_for_container_health() {
  local container_name="$1"
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
  local status=""

  echo "Waiting for ${container_name} to be healthy..."
  while [ "$SECONDS" -lt "$deadline" ]; do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_name" 2>/dev/null || true)"
    if [ "$status" = "healthy" ]; then
      return 0
    fi
    sleep 1
  done

  echo "${container_name} did not become healthy within ${HEALTH_TIMEOUT_SECONDS}s." >&2
  exit 1
}

wait_for_app_health() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))

  echo "Waiting for app to be healthy..."
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -sf localhost:8000/health > /dev/null; then
      return 0
    fi
    sleep 1
  done

  echo "App health check did not pass within ${HEALTH_TIMEOUT_SECONDS}s." >&2
  docker compose logs --tail=80 app >&2 || true
  exit 1
}

wait_for_pid_exit() {
  local pid="$1"

  while kill -0 "$pid" 2>/dev/null; do
    sleep 1
  done
}

database_tables() {
  docker compose exec -T postgres sh -lc \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select tablename from pg_tables where schemaname='\''public'\'' order by tablename;"'
}

current_alembic_revision() {
  docker compose exec -T postgres sh -lc \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version" 2>/dev/null' \
    | head -n 1 | tr -d '[:space:]'
}

revision_is_known() {
  local revision="$1"
  [ -n "$revision" ] || return 1
  grep -REq "^revision[^=]*=[[:space:]]*[\"']${revision}[\"']" \
    "$ROOT_DIR/alembic/versions" 2>/dev/null
}

column_exists() {
  local table="$1" column="$2"
  docker compose exec -T postgres sh -lc \
    "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -Atc \"select 1 from information_schema.columns where table_schema='public' and table_name='${table}' and column_name='${column}' limit 1\"" \
    2>/dev/null | grep -qx '1'
}

recover_unknown_alembic_revision() {
  # alembic_version may point at a revision file that has been renamed or
  # squashed out of this branch (e.g. a previous `alembic merge heads`
  # artifact). In that case `alembic upgrade head` fails with
  # "Can't locate revision ...". Detect it, probe the schema to figure out
  # which known revision actually matches the DB, and re-stamp so we can
  # roll forward from there.
  local current=""
  current="$(current_alembic_revision || true)"
  [ -n "$current" ] || return 0

  if revision_is_known "$current"; then
    return 0
  fi

  echo "Detected unknown alembic revision '${current}' (no migration file in this branch)."

  local tables=""
  tables="$(database_tables)"

  local target=""
  if printf '%s\n' "$tables" | grep -qx 'position_revalidations'; then
    target="0012_position_validation"
  elif printf '%s\n' "$tables" | grep -qx 'position_theses'; then
    target="0012_position_validation"
  elif printf '%s\n' "$tables" | grep -qx 'position_plan_overrides'; then
    target="0011_position_plan_overrides"
  elif column_exists recommendations expected_move_percent; then
    target="0010_safety_expected_move"
  elif column_exists recommendations news_coverage; then
    target="0009_news_coverage"
  elif column_exists open_positions target_dismissed; then
    target="0008_position_mute"
  elif column_exists open_positions pnl_applied; then
    target="0007_position_pnl_applied"
  elif printf '%s\n' "$tables" | grep -qx 'open_positions'; then
    target="0006_open_positions"
  else
    echo "Could not infer a known alembic revision that matches the current schema." >&2
    echo "Inspect the public schema and run 'alembic stamp <revision>' manually." >&2
    exit 1
  fi

  echo "Re-stamping alembic_version to '${target}' to match the existing schema..."
  # --purge clears the existing alembic_version row first; without it alembic
  # refuses to operate because the current revision is unknown.
  docker compose run --rm --no-deps app alembic stamp --purge "$target"
}

recover_stamped_but_uninitialized_db() {
  # Reset alembic_version when the DB is "stamped" (alembic_version row exists)
  # but the actual schema tables are missing. This can happen after volume
  # wipes that preserved alembic_version, or when migrations were applied
  # against a different schema. Detect early so `alembic upgrade head` does
  # not fail trying to ALTER tables that do not exist.
  local tables="" unexpected_tables=""

  tables="$(database_tables)"
  if printf '%s\n' "$tables" | grep -qx 'cron_jobs'; then
    return 0
  fi

  unexpected_tables="$(
    printf '%s\n' "$tables" | grep -v -e '^$' -e '^alembic_version$' -e '^apscheduler_jobs$' || true
  )"
  if [ -z "$unexpected_tables" ] && printf '%s\n' "$tables" | grep -qx 'alembic_version'; then
    echo "Detected a stamped-but-uninitialized local database. Resetting alembic version to base..."
    docker compose run --rm --no-deps app alembic stamp base
  fi
}

ensure_database_schema() {
  local tables=""

  tables="$(database_tables)"
  if printf '%s\n' "$tables" | grep -qx 'cron_jobs'; then
    return 0
  fi

  echo "Database schema is inconsistent after migrations. cron_jobs is still missing." >&2
  printf 'Current public tables:\n%s\n' "$tables" >&2
  exit 1
}

cleanup_bot() {
  local pid=""

  if [ -f "$BOT_PID_FILE" ]; then
    pid="$(cat "$BOT_PID_FILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait_for_pid_exit "$pid"
    fi
    rm -f "$BOT_PID_FILE"
  fi
}

stop_existing_bot() {
  local pid=""

  mkdir -p "$(dirname "$BOT_PID_FILE")"

  if [ -f "$BOT_PID_FILE" ]; then
    pid="$(cat "$BOT_PID_FILE" 2>/dev/null || true)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "Stopping previous Telegram bot..."
      kill "$pid" 2>/dev/null || true
      wait_for_pid_exit "$pid"
    fi
    rm -f "$BOT_PID_FILE"
  fi

  ps -ax -o pid=,command= | awk -v root="$ROOT_DIR/.venv/bin/python" \
    'index($0, root) && $0 ~ /-m app\.telegram\.bot/ {print $1}' |
    while IFS= read -r pid; do
      [ -n "$pid" ] || continue
      if kill -0 "$pid" 2>/dev/null; then
        echo "Stopping stray Telegram bot process (pid $pid)..."
        kill "$pid" 2>/dev/null || true
        wait_for_pid_exit "$pid"
      fi
    done
}

echo "Ensuring local Python environment is synced..."
uv sync --frozen

ensure_docker_available

echo "Starting database and cache services..."
docker compose up -d postgres redis
wait_for_container_health "earning-edge-postgres"
wait_for_container_health "earning-edge-redis"

echo "Building app image (cached layers reused when unchanged)..."
docker compose build app

echo "Applying database migrations..."
recover_stamped_but_uninitialized_db
recover_unknown_alembic_revision
docker compose run --rm --no-deps app alembic upgrade head
ensure_database_schema

echo "Starting backend..."
docker compose up -d --force-recreate app
wait_for_app_health

stop_existing_bot

echo "Backend ready. Starting Telegram bot..."
trap cleanup_bot EXIT INT TERM
REDIS_HOST=localhost REDIS_PORT=16379 POSTGRES_HOST=localhost POSTGRES_PORT=15432 \
  "$VENV_PYTHON" -m app.telegram.bot &
BOT_PID=$!
echo "$BOT_PID" > "$BOT_PID_FILE"

set +e
wait "$BOT_PID"
status=$?
set -e

rm -f "$BOT_PID_FILE"
trap - EXIT INT TERM
exit "$status"
