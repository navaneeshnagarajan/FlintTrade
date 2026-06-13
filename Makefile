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
PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,$(shell which python3 2>/dev/null || which python 2>/dev/null))
NPM := $(shell which npm 2>/dev/null)
FLINTTRADE_DIR := $(shell pwd)
FLINTTRADE_PYTHONPATH := packages/core/core/src

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
FLINTTRADE_BACKEND_PORT ?= 5100
ifeq ($(OS),Windows_NT)
  OPENALGO_PID := $(TEMP)/flinttrade-openalgo.pid
else
  OPENALGO_PID := /tmp/flinttrade-openalgo.pid
endif

.PHONY: setup start start-gateway start-openalgo start-legacy stop restart status test test-fast lint clean update dev docker-up docker-down docker-build version health help audit sync-check full-check install-docker install-native backup restore logs-clear desktop-icons desktop-backend desktop-build desktop-dev

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

start: ## Start FlintTrade backend API (standalone; OpenAlgo is optional)
	@echo -e "$(CYAN)=== Starting FlintTrade ===$(RESET)"
	@echo "  Backend: http://127.0.0.1:$(FLINTTRADE_BACKEND_PORT)"
	@echo ""
	PYTHONPATH="$(FLINTTRADE_PYTHONPATH):$${PYTHONPATH:-}" $(PYTHON) -m flinttrade_core.app

# --- Gateway mode (v0.2.0+) — single process, no separate OpenAlgo ---

start-gateway: start ## Alias for start (standalone FlintTrade backend)

start-openalgo: ## Start optional local OpenAlgo integration service
	@bash infra/scripts/openalgo/start-openalgo.sh

# Legacy mode alias — requires separate OpenAlgo instance
start-legacy: start-openalgo ## Start optional OpenAlgo integration service

stop: ## Stop FlintTrade backend API if it is listening on FLINTTRADE_BACKEND_PORT
	@if command -v lsof >/dev/null 2>&1; then \
	  pid="$$(lsof -tiTCP:$(FLINTTRADE_BACKEND_PORT) -sTCP:LISTEN 2>/dev/null | head -1)"; \
	  if [ -n "$$pid" ]; then \
	    echo -e "$(YELLOW)Stopping FlintTrade backend on port $(FLINTTRADE_BACKEND_PORT) (PID $$pid)$(RESET)"; \
	    kill "$$pid"; \
	  else \
	    echo -e "$(YELLOW)No FlintTrade backend listening on port $(FLINTTRADE_BACKEND_PORT).$(RESET)"; \
	  fi; \
	else \
	  echo -e "$(YELLOW)lsof is not available; stop the FlintTrade backend process manually.$(RESET)"; \
	fi

restart: stop start ## Restart FlintTrade backend

status: ## Show service status
	@bash infra/scripts/status.sh

health: ## Run health check
	@FLINTTRADE_HEALTH_STRICT=0 bash infra/scripts/health-check.sh

dev: ## Start terminal dev server + FlintTrade backend
	@echo -e "$(CYAN)=== FlintTrade Dev Mode ===$(RESET)"
	@echo "  Terminal:  http://127.0.0.1:5173"
	@echo "  Backend:   http://127.0.0.1:$(FLINTTRADE_BACKEND_PORT)"
	@echo "  OpenAlgo:  optional integration, configure in Settings when needed"
	@echo ""
	@mkdir -p .local/dev-logs
	@set -e; \
	  PYTHONPATH="$(FLINTTRADE_PYTHONPATH):$${PYTHONPATH:-}" $(PYTHON) -m flinttrade_core.app > .local/dev-logs/backend.log 2>&1 & \
	  backend_pid="$$!"; \
	  if [ -n "$(NPM)" ]; then \
	    (cd packages/apps/terminal && npm run dev) > "$(FLINTTRADE_DIR)/.local/dev-logs/terminal.log" 2>&1 & \
	    terminal_pid="$$!"; \
	  else \
	    echo -e "$(RED)npm not found; terminal dev server was not started.$(RESET)"; \
	    terminal_pid=""; \
	  fi; \
	  echo -e "$(GREEN)Started backend PID $$backend_pid and terminal PID $${terminal_pid:-none}.$(RESET)"; \
	  echo "Logs: .local/dev-logs/backend.log and .local/dev-logs/terminal.log"; \
	  trap 'kill "$$backend_pid" $${terminal_pid:-} 2>/dev/null || true' INT TERM EXIT; \
	  wait

# ======================================================================
# Testing and quality
# ======================================================================

test: ## Run all tests
ifeq ($(OS),Windows_NT)
	@$(PYTHON) -m pytest packages/core/core/tests/ packages/services/engine/tests/ packages/integrations/gateway/tests/ packages/services/screener/tests/ packages/core/data/tests/ packages/core/historical/tests/ packages/core/indicators/tests/ packages/services/ai/tests/ packages/services/automation/tests/ packages/services/backtest/tests/ packages/services/ditto/tests/ packages/services/journal/tests/ packages/integrations/webhooks/tests/ tests/ -v --tb=short --import-mode=importlib
else
	@$(PYTHON) -m pytest packages/*/*/tests/ tests/ -v --tb=short --import-mode=importlib
endif

test-fast: ## Run tests, stop on first failure
ifeq ($(OS),Windows_NT)
	@$(PYTHON) -m pytest packages/core/core/tests/ packages/services/engine/tests/ packages/integrations/gateway/tests/ packages/services/screener/tests/ packages/core/data/tests/ packages/core/historical/tests/ packages/core/indicators/tests/ packages/services/ai/tests/ packages/services/automation/tests/ packages/services/backtest/tests/ packages/services/ditto/tests/ packages/services/journal/tests/ packages/integrations/webhooks/tests/ tests/ -x --tb=short --import-mode=importlib
else
	@$(PYTHON) -m pytest packages/*/*/tests/ tests/ -x --tb=short --import-mode=importlib
endif

lint: ## Run linter (ruff)
ifeq ($(OS),Windows_NT)
	@$(PYTHON) -m ruff check packages/ tests/ || echo ruff not installed. Install with: pip install ruff
else
	@$(PYTHON) -m ruff check packages/ tests/ || echo ruff not installed. Install with: pip install ruff
endif

# ======================================================================
# Native desktop app (Tauri 2 shell + PyInstaller backend sidecar)
# ======================================================================
# Produces installable packages (.dmg/.app, .msi/.exe, .deb/.rpm/.AppImage).
# Each target builds for the CURRENT OS/arch; the full cross-platform matrix is
# produced by .github/workflows/desktop-release.yml. See docs/DESKTOP.md.

desktop-icons: ## Regenerate the desktop app icons from the brand mark
	@$(PYTHON) packaging/make-icons.py

desktop-backend: ## Freeze the backend into a Tauri sidecar (current OS/arch)
	@PYTHON="$(PYTHON)" bash packaging/build-backend.sh

desktop-build: ## Build native desktop installers for this OS (frontend + sidecar + bundle)
	@PYTHON="$(PYTHON)" bash packaging/build-backend.sh
	@cd packages/apps/desktop && pnpm install && pnpm tauri build
	@echo -e "$(GREEN)✓ Installers under packages/apps/desktop/src-tauri/target/release/bundle/$(RESET)"

desktop-dev: ## Run the desktop app in dev mode (builds the sidecar first)
	@PYTHON="$(PYTHON)" bash packaging/build-backend.sh
	@cd packages/apps/desktop && pnpm install && pnpm tauri dev

# ======================================================================
# Maintenance
# ======================================================================

update: ## Update Python dependencies (external test-deps live in .local/external/, update them yourself)
	@echo "Updating Python dependencies..."
	@$(PYTHON) -m pip install -r requirements.txt --upgrade --break-system-packages -q 2>/dev/null || \
	 $(PYTHON) -m pip install -r requirements.txt --upgrade -q
	@echo -e "$(GREEN)✓ Updated$(RESET)"
	@echo -e "$(YELLOW)Note: external test-deps under .local/external/ are not git submodules anymore.$(RESET)"
	@echo -e "$(YELLOW)Pull updates manually: cd .local/external/openalgo && git pull (etc.)$(RESET)"

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
	@set -o pipefail; $(PYTHON) -m pytest packages/integrations/gateway/tests/ packages/core/core/tests/ packages/services/screener/tests/ packages/services/engine/tests/ -q --no-header --import-mode=importlib 2>&1 | tail -3
	@echo -e "$(YELLOW)--- Ruff Lint ---$(RESET)"
	@set -o pipefail; $(PYTHON) -m ruff check packages/*/*/src/ --statistics 2>&1 | tail -5
	@echo -e "$(YELLOW)--- Terminal ---$(RESET)"
	@cd packages/apps/terminal && set -o pipefail; npm run typecheck 2>&1 | tail -2
	@cd packages/apps/terminal && set -o pipefail; npx vitest run 2>&1 | tail -3
	@echo -e "$(GREEN)=== Done ===$(RESET)"

audit: ## Check repo absorption status
	@$(PYTHON) scripts/audit_repos.py

sync-check: ## Check upstream drift on external test-deps under .local/external/
	@echo -e "$(CYAN)=== External Test-Deps Sync Check ===$(RESET)"
	@if [ -d .local/external/openalgo/.git ]; then \
	  (cd .local/external/openalgo && git fetch origin --quiet 2>/dev/null && echo "openalgo: $$(git rev-list HEAD..origin/main --count 2>/dev/null || echo '?') commits behind"); \
	else \
	  echo -e "$(YELLOW)openalgo: not present at .local/external/openalgo (run scripts/setup-test-deps.sh)$(RESET)"; \
	fi
	@if [ -d .local/external/openclaw/.git ]; then \
	  (cd .local/external/openclaw && git fetch origin --quiet 2>/dev/null && echo "openclaw: $$(git rev-list HEAD..origin/main --count 2>/dev/null || echo '?') commits behind"); \
	else \
	  echo -e "$(YELLOW)openclaw: not present at .local/external/openclaw (run scripts/setup-test-deps.sh)$(RESET)"; \
	fi

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
