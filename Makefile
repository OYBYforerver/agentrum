.PHONY: compose-up migrate serve test lint

compose-up: ## Start postgres (dev)
	docker compose up -d --wait postgres

migrate: ## Run database migrations
	uv run alembic upgrade head

serve: ## Run API locally on :12121
	uv run uvicorn agentrum.main:app --reload --port 12121

test: ## Run unit tests
	uv run pytest

lint: ## Lint with ruff
	uv run ruff check src tests
