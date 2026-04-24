# FlintTrade Makefile
# Usage: make help
#
# ============================================================================
# Windows compatibility
# ============================================================================
# The following targets work natively on Windows (via GNU Make + Python/npm):
#   make test, make test-fast, make lint, make docker-up, make docker-down,
#   make docker-build, make version, make help, make full-check
#
# The following targets require WSL2 or Docker on Windows (they use bash
# scripts, systemd, or Linux-only tools):
#   make start, make stop, make restart, make dev, make status, make health,
#   make setup, make update, make clean, make install-docker, make install-native,
#   make backup, make restore, make sync-check, make audit
# ============================================================================

SHELL := /usr/bin/env bash
PYTHON := $(shell which python3 2>/dev/null || which python 2>/dev/null)
NPM := $(shell which npm 2>/dev/null)
FLINTTRADE_DIR := $(shell pwd)

# Colors
GREEN  := \033[32m
RED    := \033[31m
YELLOW := \033[33m
CYAN   := \033[36m
RESET  := \033[0m

# Source .env if it exists
ifneq (,$(wildcard .env))
  include .env
  export
endif

OPENALGO_PORT ?= 5000
ifeq ($(OS),Windows_NT)
  OPENALGO_PID := $(TEMP)/flinttrade-openalgo.pid
else
  OPENALGO_PID := /tmp/flinttrade-openalgo.pid
endif

.PHONY: setup start start-gateway start-legacy stop restart status test test-fast lint clean update dev docker-up docker-down docker-build version health help audit sync-check full-check install-docker install-native backup restore logs-clear

# ======================================================================
# Setup
# ======================================================================

setup: check-python ## First-time setup — install all dependencies
	@bash infra/scripts/setup.sh

check-python: ## Verify Python >= 3.11 (required for StrEnum)
	@$(PYTHON) -c "import sys; v=sys.version_info; exit(0 if v >= (3,11) else 1)" 2>/dev/null || \
	  (echo -e "$(RED)Error: Python 3.11+ required (StrEnum support). Found: $$($(PYTHON) --version)$(RESET)"; exit 1)

# ======================================================================
# Service management
# ======================================================================

start: ## Start OpenAlgo service
	@echo -e "$(CYAN)=== Starting FlintTrade ===$(RESET)"
	@bash infra/scripts/openalgo/start-openalgo.sh
	@echo -e "$(GREEN)=== FlintTrade running ===$(RESET)"

# --- Gateway mode (v0.2.0+) — single process, no separate OpenAlgo ---

start-gateway: ## Start FlintTrade gateway backend (standalone, no OpenAlgo)
	$(PYTHON) -m packages.core.src.app

# Legacy mode alias — requires separate OpenAlgo instance (same as `start`)
start-legacy: start ## Start in legacy mode (requires separate OpenAlgo instance)

stop: ## Stop OpenAlgo service
	@bash infra/scripts/openalgo/stop-openalgo.sh

restart: stop start ## Restart OpenAlgo

status: ## Show service status
	@bash infra/scripts/status.sh

health: ## Run health check
	@bash infra/scripts/health-check.sh

dev: ## Start terminal dev server + OpenAlgo
	@echo -e "$(CYAN)=== FlintTrade Dev Mode ===$(RESET)"
	@echo "  Terminal:  http://localhost:5173"
	@echo "  OpenAlgo:  http://localhost:$(OPENALGO_PORT)"
	@echo ""
	@if [ -n "$(NPM)" ]; then \
	  cd packages/terminal && npm run dev & \
	fi
	@bash infra/scripts/openalgo/start-openalgo.sh

# ======================================================================
# Testing and quality
# ======================================================================

test: ## Run all tests
ifeq ($(OS),Windows_NT)
	@$(PYTHON) -m pytest packages/core/tests/ packages/engine/tests/ packages/gateway/tests/ packages/screener/tests/ packages/data/tests/ packages/historical/tests/ packages/indicators/tests/ packages/ai/tests/ packages/automation/tests/ packages/backtest-engine/tests/ packages/integration/tests/ tests/ -v --tb=short --import-mode=importlib
else
	@$(PYTHON) -m pytest packages/*/tests/ tests/ -v --tb=short --import-mode=importlib
endif

test-fast: ## Run tests, stop on first failure
ifeq ($(OS),Windows_NT)
	@$(PYTHON) -m pytest packages/core/tests/ packages/engine/tests/ packages/gateway/tests/ packages/screener/tests/ packages/data/tests/ packages/historical/tests/ packages/indicators/tests/ packages/ai/tests/ packages/automation/tests/ packages/backtest-engine/tests/ packages/integration/tests/ tests/ -x --tb=short --import-mode=importlib
else
	@$(PYTHON) -m pytest packages/*/tests/ tests/ -x --tb=short --import-mode=importlib
endif

lint: ## Run linter (ruff)
ifeq ($(OS),Windows_NT)
	@$(PYTHON) -m ruff check packages/ tests/ || echo ruff not installed. Install with: pip install ruff
else
	@if command -v ruff >/dev/null 2>&1; then \
	  ruff check packages/ tests/; \
	else \
	  echo -e "$(YELLOW)ruff not installed. Install with: pip install ruff$(RESET)"; \
	fi
endif

# ======================================================================
# Maintenance
# ======================================================================

update: ## Update submodules and dependencies
	@echo "Updating submodules..."
	@git submodule update --remote --merge 2>/dev/null || true
	@echo "Updating Python dependencies..."
	@$(PYTHON) -m pip install -r requirements.txt --upgrade --break-system-packages -q 2>/dev/null || \
	 $(PYTHON) -m pip install -r requirements.txt --upgrade -q
	@echo -e "$(GREEN)✓ Updated$(RESET)"

clean: ## Remove build artifacts (with confirmation)
	@echo "This will remove __pycache__, .pytest_cache, and node_modules."
	@read -p "Continue? [y/N] " confirm && [ "$$confirm" = "y" ] || exit 0
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find packages -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true
	@echo -e "$(GREEN)✓ Cleaned$(RESET)"

# ======================================================================
# Docker
# ======================================================================

docker-up: ## Start all services with Docker
	docker compose up

docker-down: ## Stop Docker services
	docker compose down

docker-build: ## Rebuild Docker images
	docker compose build

# ======================================================================
# Management
# ======================================================================

full-check: ## Run full health check (tests + lint + typecheck)
	@echo -e "$(CYAN)=== FlintTrade Health Check ===$(RESET)"
	@echo -e "$(YELLOW)--- Python Tests ---$(RESET)"
	@$(PYTHON) -m pytest packages/gateway/tests/ packages/core/tests/ packages/screener/tests/ packages/engine/tests/ -q --no-header --import-mode=importlib 2>&1 | tail -3
	@echo -e "$(YELLOW)--- Ruff Lint ---$(RESET)"
	@$(PYTHON) -m ruff check packages/*/src/ --statistics 2>&1 | tail -5
	@echo -e "$(YELLOW)--- Terminal ---$(RESET)"
	@cd packages/terminal && npm run typecheck 2>&1 | tail -2
	@cd packages/terminal && npx vitest run 2>&1 | tail -3
	@echo -e "$(GREEN)=== Done ===$(RESET)"

audit: ## Check repo absorption status
	@$(PYTHON) scripts/audit_repos.py

sync-check: ## Check submodule upstream changes
	@echo -e "$(CYAN)=== Submodule Sync Check ===$(RESET)"
	@cd infra/openalgo && git fetch origin --quiet 2>/dev/null && echo "openalgo: $$(git rev-list HEAD..origin/main --count 2>/dev/null || echo '?') commits behind" || echo "openalgo: not available"
	@cd infra/algomirror && git fetch origin --quiet 2>/dev/null && echo "algomirror: $$(git rev-list HEAD..origin/main --count 2>/dev/null || echo '?') commits behind" || echo "algomirror: not available"
	@cd infra/openclaw && git fetch origin --quiet 2>/dev/null && echo "openclaw: $$(git rev-list HEAD..origin/main --count 2>/dev/null || echo '?') commits behind" || echo "openclaw: not available"

logs-clear: ## Truncate runtime .log files under .local/dev-logs/
	@echo -e "$(CYAN)=== Clearing runtime logs ===$(RESET)"
	@mkdir -p .local/dev-logs
	@for f in .local/dev-logs/*.log; do \
	  [ -e "$$f" ] || continue; \
	  size=$$(du -h "$$f" 2>/dev/null | cut -f1); \
	  : > "$$f"; \
	  echo "  truncated $$f ($$size -> 0)"; \
	done
	@touch .local/dev-logs/.gitkeep
	@echo -e "$(GREEN)=== Logs cleared ===$(RESET)"

# ======================================================================
# Installation and backup
# ======================================================================

install-docker: ## Install FlintTrade with Docker (production)
	@bash infra/install/install-docker.sh

install-native: ## Install FlintTrade on bare metal (Ubuntu/Debian)
	@bash infra/install/install-native.sh

backup: ## Run restic backup of FlintTrade data
	@bash infra/backup/backup.sh

restore: ## Restore FlintTrade data from restic backup
	@bash infra/backup/restore.sh

# ======================================================================
# Info
# ======================================================================

version: ## Show version
	@cat VERSION

help: ## Show this help
	@echo -e "$(CYAN)FlintTrade$(RESET) — make targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-15s$(RESET) %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
