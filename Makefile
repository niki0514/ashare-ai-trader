.PHONY: db-up db-down dev-up dev-docker-up dev-docker-down dev-docker-logs

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

dev-up:
	./scripts/dev-up.sh

dev-docker-up:
	docker compose --profile dev up --build

dev-docker-down:
	docker compose --profile dev down

dev-docker-logs:
	docker compose --profile dev logs -f backend frontend
