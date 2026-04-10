# ===========================================================================
# PULSE - Development Makefile
# ===========================================================================

COMPOSE := docker compose
COMPOSE_TEST := docker compose -f docker-compose.test.yml

.PHONY: help up down dev logs clean setup \
        test test-unit test-integration \
        migrate seed lint fmt build

# --------------------------------------------------------------------------
# Help
# --------------------------------------------------------------------------
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------------------
# Docker Compose -Lifecycle
# --------------------------------------------------------------------------
up: ## Start all backend services (APIs + infra)
	$(COMPOSE) up -d
	@echo ""
	@echo "Services started. Run 'make dev' in another terminal for frontend."
	@echo "  API:     http://localhost:3000"
	@echo "  Data:    http://localhost:8000"

down: ## Stop all services
	$(COMPOSE) down

clean: ## Stop services and remove volumes
	$(COMPOSE) down -v --remove-orphans
	$(COMPOSE_TEST) down -v --remove-orphans 2>/dev/null || true

logs: ## Tail logs from all services
	$(COMPOSE) logs -f

# --------------------------------------------------------------------------
# Frontend (runs outside Docker)
# --------------------------------------------------------------------------
dev: ## Start frontend dev server (Vite HMR on :5173)
	cd packages/pulse-web && npm run dev

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
migrate: ## Run database migrations
	$(COMPOSE) exec pulse-api npm run migration:run
	$(COMPOSE) exec pulse-data alembic upgrade head

seed: ## Seed database with config/connections.yaml data
	$(COMPOSE) exec pulse-api npm run seed

# --------------------------------------------------------------------------
# Testing
# --------------------------------------------------------------------------
test: test-unit test-integration ## Run all tests

test-unit: ## Run unit tests (Jest + Pytest + Vitest)
	cd packages/pulse-api && npm run test
	cd packages/pulse-data && python -m pytest tests/unit -v
	cd packages/pulse-web && npm run test

test-integration: ## Run integration tests (requires Docker services)
	$(COMPOSE_TEST) up -d --wait
	cd packages/pulse-api && npm run test:integration
	cd packages/pulse-data && python -m pytest tests/integration -v
	$(COMPOSE_TEST) down -v

# --------------------------------------------------------------------------
# Code Quality
# --------------------------------------------------------------------------
lint: ## Run linters (ESLint + Ruff)
	cd packages/pulse-api && npm run lint
	cd packages/pulse-web && npm run lint
	cd packages/pulse-data && ruff check src tests
	cd packages/pulse-shared && npm run typecheck

fmt: ## Format code (Prettier + Black)
	cd packages/pulse-api && npx prettier --write "src/**/*.ts"
	cd packages/pulse-web && npx prettier --write "src/**/*.{ts,tsx}"
	cd packages/pulse-data && ruff format src tests
	cd packages/pulse-data && black src tests

# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------
build: ## Build all packages
	cd packages/pulse-shared && npm run build
	cd packages/pulse-api && npm run build
	cd packages/pulse-web && npm run build
	$(COMPOSE) build

# --------------------------------------------------------------------------
# First-time Setup
# --------------------------------------------------------------------------
setup: ## First-time setup: install deps, copy env, start services, migrate
	@echo "=== PULSE First-Time Setup ==="
	@test -f .env || cp .env.example .env
	cd packages/pulse-shared && npm install && npm run build
	cd packages/pulse-api && npm install
	cd packages/pulse-web && npm install
	cd packages/pulse-data && pip install -r requirements.txt
	$(COMPOSE) up -d --wait
	@echo ""
	@echo "Waiting for services to be healthy..."
	@sleep 5
	$(MAKE) migrate
	@echo ""
	@echo "=== Setup Complete ==="
	@echo "Run 'make dev' to start the frontend dev server."
	@echo "Run 'make logs' to see backend logs."
