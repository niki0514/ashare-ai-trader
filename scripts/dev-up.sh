#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
POSTGRES_CONTAINER="ashare-postgres"
DEFAULT_DEV_DATABASE_URL="postgresql+psycopg://ashare:ashare@127.0.0.1:5433/ashare_ai_trader"
BACKUP_FILE="${1:-}"

BACKEND_PID=""
FRONTEND_PID=""

export ASHARE_DATABASE_URL="${ASHARE_DATABASE_URL:-$DEFAULT_DEV_DATABASE_URL}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

cleanup() {
  if [[ -n "$BACKEND_PID" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi

  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi
}

handle_signal() {
  trap - INT TERM EXIT
  cleanup
  exit 130
}

wait_for_postgres() {
  local status=""
  local retries=60

  for ((i = 1; i <= retries; i++)); do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$POSTGRES_CONTAINER" 2>/dev/null || true)"
    if [[ "$status" == "healthy" || "$status" == "running" ]]; then
      return 0
    fi
    sleep 1
  done

  echo "PostgreSQL did not become ready in time. Last status: ${status:-unknown}" >&2
  exit 1
}

init_backend_schema() {
  (
    cd "$BACKEND_DIR"
    uv run python -m devtools.schema init
  )
}

start_backend() {
  (
    cd "$BACKEND_DIR"
    exec env ASHARE_RELOAD=true uv run python -m app
  ) &
  BACKEND_PID=$!
}

start_frontend() {
  (
    cd "$FRONTEND_DIR"
    exec npm run dev -- --host 0.0.0.0
  ) &
  FRONTEND_PID=$!
}

monitor_processes() {
  while true; do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      wait "$BACKEND_PID"
      return $?
    fi

    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
      wait "$FRONTEND_PID"
      return $?
    fi

    sleep 1
  done
}

restore_backup_if_requested() {
  if [[ -z "$BACKUP_FILE" ]]; then
    return 0
  fi

  if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "Backup file not found: $BACKUP_FILE" >&2
    exit 1
  fi

  echo "Restoring database from $BACKUP_FILE ..."
  ASHARE_COMPOSE_FILE=docker-compose.yml "$ROOT_DIR/scripts/restore-db.sh" "$BACKUP_FILE"
}

require_command docker
require_command uv
require_command npm

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "frontend/node_modules missing, running npm install..."
  (
    cd "$FRONTEND_DIR"
    npm install
  )
fi

trap handle_signal INT TERM
trap cleanup EXIT

echo "Starting PostgreSQL container..."
(
  cd "$ROOT_DIR"
  docker compose up -d postgres
)

echo "Waiting for PostgreSQL to become healthy..."
wait_for_postgres

restore_backup_if_requested

echo "Ensuring backend schema exists..."
init_backend_schema

echo "Starting backend on http://localhost:3101 ..."
start_backend

echo "Starting frontend on http://localhost:5174 ..."
start_frontend

echo "Stack is starting in hot-reload mode. Press Ctrl+C to stop frontend and backend."
monitor_processes
