#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${ASHARE_COMPOSE_FILE:-docker-compose.yml}"
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
      if docker exec "$container_id" pg_isready -U "$POSTGRES_USER" -d postgres >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 1
  done

  echo "PostgreSQL did not become ready in time. Last status: ${status:-unknown}" >&2
  exit 1
}

ensure_database_exists() {
  local container_id="$1"
  local exists

  exists="$(
    docker exec "$container_id" psql -U "$POSTGRES_USER" -d postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB';"
  )"

  if [[ "$exists" == "1" ]]; then
    return 0
  fi

  docker exec "$container_id" createdb -U "$POSTGRES_USER" "$POSTGRES_DB"
}

terminate_existing_connections() {
  local container_id="$1"

  docker exec "$container_id" psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$POSTGRES_DB' AND pid <> pg_backend_pid();" \
    >/dev/null
}

restore_custom_dump() {
  local container_id="$1"
  local backup_file="$2"

  docker exec -i "$container_id" pg_restore \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" < "$backup_file"
}

restore_sql_dump() {
  local container_id="$1"
  local backup_file="$2"

  docker exec -i "$container_id" psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$backup_file"
}

require_command docker

BACKUP_FILE="${1:-}"
if [[ -z "$BACKUP_FILE" ]]; then
  echo "Usage: $0 /absolute/or/relative/path/to/backup.dump" >&2
  exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "Backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

echo "Starting PostgreSQL service (compose file: $COMPOSE_FILE) ..."
compose up -d postgres >/dev/null

CONTAINER_ID="$(postgres_container_id)"
if [[ -z "$CONTAINER_ID" ]]; then
  echo "Failed to locate postgres container for compose file: $COMPOSE_FILE" >&2
  exit 1
fi

echo "Waiting for PostgreSQL to become ready..."
wait_for_postgres "$CONTAINER_ID"
ensure_database_exists "$CONTAINER_ID"
terminate_existing_connections "$CONTAINER_ID"

echo "Restoring database from $BACKUP_FILE ..."
case "$BACKUP_FILE" in
  *.sql)
    restore_sql_dump "$CONTAINER_ID" "$BACKUP_FILE"
    ;;
  *)
    restore_custom_dump "$CONTAINER_ID" "$BACKUP_FILE"
    ;;
esac

echo "Database restored into $POSTGRES_DB"
