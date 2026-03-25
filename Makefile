.PHONY: db-up db-down bootstrap dev-up

db-up:
	docker compose up -d postgres

db-down:
	docker compose down

bootstrap:
	cd backend && uv run python -m app.bootstrap

dev-up:
	./scripts/dev-up.sh
