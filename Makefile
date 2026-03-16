# FlintTrade Makefile
# Usage: make help

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
OPENALGO_PID := /tmp/flinttrade-openalgo.pid

.PHONY: setup start stop restart status test test-fast lint clean update dev docker-up docker-down docker-build version health help

# ======================================================================
# Setup
# ======================================================================

setup: ## First-time setup — install all dependencies
	@bash infra/scripts/setup.sh

# ======================================================================
# Service management
# ======================================================================

start: ## Start OpenAlgo service
	@echo -e "$(CYAN)=== Starting FlintTrade ===$(RESET)"
	@bash infra/scripts/start-openalgo.sh
	@echo -e "$(GREEN)=== FlintTrade running ===$(RESET)"

stop: ## Stop OpenAlgo service
	@bash infra/scripts/stop-openalgo.sh

restart: stop start ## Restart OpenAlgo

status: ## Show service status
	@bash infra/scripts/status.sh

health: ## Run health check
	@bash infra/scripts/health-check.sh

dev: ## Start React dev servers + backend
	@echo -e "$(CYAN)=== FlintTrade Dev Mode ===$(RESET)"
	@echo "  Terminal:  http://localhost:3001"
	@echo "  Dashboard: http://localhost:3000"
	@echo "  Backtest:  http://localhost:3002"
	@echo "  OpenAlgo:  http://localhost:$(OPENALGO_PORT)"
	@echo ""
	@if [ -n "$(NPM)" ]; then \
	  cd packages/terminal && npm run dev & \
	  cd packages/dashboard && npm run dev & \
	  cd packages/backtest && npm run dev & \
	fi
	@bash infra/scripts/start-openalgo.sh

# ======================================================================
# Testing and quality
# ======================================================================

test: ## Run all tests
	@$(PYTHON) -m pytest packages/*/tests/ tests/ -v --tb=short --import-mode=importlib

test-fast: ## Run tests, stop on first failure
	@$(PYTHON) -m pytest packages/*/tests/ tests/ -x --tb=short --import-mode=importlib

lint: ## Run linter (ruff)
	@if command -v ruff >/dev/null 2>&1; then \
	  ruff check packages/ tests/; \
	else \
	  echo -e "$(YELLOW)ruff not installed. Install with: pip install ruff$(RESET)"; \
	fi

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
