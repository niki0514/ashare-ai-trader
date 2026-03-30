.PHONY: db-up db-down db-backup db-restore dev-up migrate-up dev-docker-up dev-docker-down dev-docker-logs

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

db-backup:
	./scripts/backup-db.sh

db-restore:
	@test -n "$(BACKUP)" || (echo "Usage: make db-restore BACKUP=backups/ashare_ai_trader_YYYYMMDD_HHMMSS.dump" >&2; exit 1)
	./scripts/restore-db.sh "$(BACKUP)"

dev-up:
	./scripts/dev-up.sh

migrate-up:
	@test -n "$(BACKUP)" || (echo "Usage: make migrate-up BACKUP=backups/ashare_ai_trader_YYYYMMDD_HHMMSS.dump" >&2; exit 1)
	./scripts/dev-up.sh "$(BACKUP)"

dev-docker-up:
	docker compose --profile dev up --build

dev-docker-down:
	docker compose --profile dev down

dev-docker-logs:
	docker compose --profile dev logs -f backend frontend
