# ===========================================================================
# PULSE - Development Makefile
# ===========================================================================

COMPOSE := docker compose
COMPOSE_TEST := docker compose -f docker-compose.test.yml

.PHONY: help up down dev logs clean setup \
        test test-unit test-integration \
        migrate seed lint fmt build \
        rotate-secrets check-secrets

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
# Secret rotation
#
# `docker compose restart` reinicia o PROCESSO no container existente e
# NÃO relê o .env. Depois de trocar um secret no .env você precisa
# recriar o container. Este target faz o passo certo:
#   docker compose up -d --force-recreate <serviços-que-usam-secrets>
# que destrói o container e recria lendo o .env do disco.
#
# Lista de serviços: workers Python que fazem chamadas autenticadas a
# source systems (GitHub, Jira, Jenkins, etc.). Se adicionar um novo
# worker/serviço que lê secrets do .env, adicione ele aqui também.
#
# Ver runbook completo em: docs/testing-playbook.md §8.9
# --------------------------------------------------------------------------
rotate-secrets: ## Re-create containers that consume .env after a secret rotation
	@echo "=== Recriando containers que leem .env ==="
	$(COMPOSE) up -d --force-recreate sync-worker discovery-worker metrics-worker pulse-data pulse-api
	@echo ""
	@echo "=== Pronto. Verifique autenticação com: ==="
	@echo "  make check-secrets"

check-secrets: ## Validate auth to external sources (GitHub, Jira) without exposing the token
	@echo "=== Verificando autenticação ==="
	@if [ ! -f .env ]; then echo "ERROR: pulse/.env não existe"; exit 1; fi
	@TOKEN=$$(grep ^GITHUB_TOKEN .env | cut -d= -f2-); \
	if [ -z "$$TOKEN" ]; then \
		echo "GITHUB_TOKEN: não configurado em .env (skip)"; \
	else \
		printf "GITHUB /user:                  HTTP "; \
		curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $$TOKEN" https://api.github.com/user; \
		ORG=$$(grep ^GITHUB_ORG .env | cut -d= -f2- | tr -d '"'); \
		if [ -n "$$ORG" ]; then \
			printf "GITHUB /orgs/%s/repos:  HTTP " "$$ORG"; \
			curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $$TOKEN" "https://api.github.com/orgs/$$ORG/repos?per_page=1"; \
		fi; \
	fi
	@JIRA_URL=$$(grep ^JIRA_BASE_URL .env 2>/dev/null | cut -d= -f2- | tr -d '"'); \
	JIRA_USER=$$(grep ^JIRA_EMAIL .env 2>/dev/null | cut -d= -f2- | tr -d '"'); \
	JIRA_TOKEN=$$(grep ^JIRA_API_TOKEN .env 2>/dev/null | cut -d= -f2-); \
	if [ -n "$$JIRA_URL" ] && [ -n "$$JIRA_USER" ] && [ -n "$$JIRA_TOKEN" ]; then \
		printf "JIRA /myself:                  HTTP "; \
		curl -s -o /dev/null -w "%{http_code}\n" -u "$$JIRA_USER:$$JIRA_TOKEN" "$$JIRA_URL/rest/api/3/myself"; \
	else \
		echo "JIRA: credenciais incompletas em .env (skip)"; \
	fi
	@echo ""
	@echo "Esperado: 200 em todos os checks ativos. 401/403 = problema de scope/aprovação."

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
