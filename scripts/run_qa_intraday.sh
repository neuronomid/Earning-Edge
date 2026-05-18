#!/usr/bin/env bash
# Linux companion to run_qa_intraday.ps1.
# Invoked by cron or a systemd timer every 20m during NYSE hours.
# The Python entry point performs its own market-hours guard, so off-hours
# launches exit cleanly with status=market_closed.

set -u
set -o pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

log_dir="$repo_root/var/qa/_scheduler"
mkdir -p "$log_dir"
log_file="$log_dir/$(date +%Y-%m-%d).log"

stamp() { date +%Y-%m-%dT%H:%M:%S%z; }
log_line() { printf '%s  %s\n' "$(stamp)" "$*" >> "$log_file"; }

if [[ -x "$repo_root/.venv/bin/python" ]]; then
    python_bin="$repo_root/.venv/bin/python"
elif command -v uv >/dev/null 2>&1; then
    python_bin="uv run python"
else
    python_bin="python3"
fi

log_line "launch python=$python_bin args=$*"

# shellcheck disable=SC2086
$python_bin "$repo_root/scripts/run_qa_intraday.py" "$@" >> "$log_file" 2>&1
code=$?

log_line "exit code=$code"
exit $code
