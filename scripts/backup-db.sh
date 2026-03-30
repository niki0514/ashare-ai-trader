#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ASHARE_COMPOSE_FILE:-docker-compose.yml}"
BACKUP_DIR="${ASHARE_BACKUP_DIR:-$ROOT_DIR/backups}"
POSTGRES_DB="${ASHARE_POSTGRES_DB:-ashare_ai_trader}"
POSTGRES_USER="${ASHARE_POSTGRES_USER:-ashare}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

compose() {
  (
    cd "$ROOT_DIR"
    docker compose -f "$COMPOSE_FILE" "$@"
  )
}

postgres_container_id() {
  compose ps -q postgres
}

wait_for_postgres() {
  local container_id="$1"
  local status=""
  local retries=60

  for ((i = 1; i <= retries; i++)); do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || true)"
    if [[ "$status" == "healthy" || "$status" == "running" ]]; then
      if docker exec "$container_id" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 1
  done

  echo "PostgreSQL did not become ready in time. Last status: ${status:-unknown}" >&2
  exit 1
}

require_command docker

mkdir -p "$BACKUP_DIR"

echo "Starting PostgreSQL service (compose file: $COMPOSE_FILE) ..."
compose up -d postgres >/dev/null

CONTAINER_ID="$(postgres_container_id)"
if [[ -z "$CONTAINER_ID" ]]; then
  echo "Failed to locate postgres container for compose file: $COMPOSE_FILE" >&2
  exit 1
fi

echo "Waiting for PostgreSQL to become ready..."
wait_for_postgres "$CONTAINER_ID"

TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
BACKUP_FILE="$BACKUP_DIR/${POSTGRES_DB}_${TIMESTAMP}.dump"

echo "Exporting database $POSTGRES_DB ..."
docker exec "$CONTAINER_ID" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$BACKUP_FILE"

echo "Backup created: $BACKUP_FILE"
