.PHONY: compose-up migrate serve test test-integration lint

compose-up: ## Start postgres (dev)
	docker compose up -d --wait postgres

migrate: ## Run database migrations
	uv run alembic upgrade head

serve: ## Run API locally on :12122
	uv run uvicorn agentrum.main:app --reload --port 12122

test: ## Run unit tests
	uv run pytest -q

test-integration: ## Run integration tests (needs postgres on :5433)
	ARK_INTEGRATION=1 uv run pytest tests/integration -q

lint: ## Lint with ruff
	uv run ruff check src tests
