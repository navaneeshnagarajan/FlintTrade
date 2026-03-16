.PHONY: setup start stop dev update test lint clean deploy rollback backup health docker-up docker-down docker-build help

setup: ## First-time setup — Linux/macOS native (see docs/setup/ for Windows)
	@echo "=== FlintTrade Setup ==="
	@echo "Cloning OpenAlgo..."
	@[ -d "infra/openalgo/.git" ] || git subtree add --prefix=infra/openalgo https://github.com/marketcalls/openalgo.git main --squash 2>/dev/null || true
	@echo "Installing Python deps..."
	@pip install --break-system-packages -r requirements.txt 2>/dev/null || pip install -r requirements.txt
	@for pkg in packages/*/requirements.txt; do [ -f "$$pkg" ] && pip install --break-system-packages -r "$$pkg" 2>/dev/null || pip install -r "$$pkg" 2>/dev/null; done
	@echo "Installing Node deps..."
	@for pkg in packages/*/package.json; do [ -f "$$pkg" ] && (cd "$$(dirname $$pkg)" && npm install && cd -); done
	@echo "✅ FlintTrade setup complete"

start: ## Start all services
	@echo "Starting FlintTrade..."
	@sudo systemctl start openalgo 2>/dev/null || echo "OpenAlgo: start manually via systemd or infra/openalgo"
	@python packages/core/src/app.py

dev: ## Start all dev servers (React + Python backend)
	@echo "=== FlintTrade Dev Mode ==="
	@echo "  Terminal:  http://localhost:3001"
	@echo "  Dashboard: http://localhost:3000"
	@echo "  Backtest:  http://localhost:3002"
	@echo "  Backend:   OpenAlgo at $${OPENALGO_HOST:-http://127.0.0.1:5000}"
	@echo ""
	@cd packages/terminal && npm run dev &
	@cd packages/dashboard && npm run dev &
	@cd packages/backtest && npm run dev &
	@python packages/core/src/app.py

stop: ## Stop all services
	@sudo systemctl stop openalgo 2>/dev/null || echo "Manual stop required"

update: ## Pull latest from all upstreams
	@git subtree pull --prefix=infra/openalgo https://github.com/marketcalls/openalgo.git main --squash
	@git pull origin dev
	@echo "✅ Updated"

test: ## Run all tests
	@python -m pytest packages/*/tests/ tests/ -v --tb=short --import-mode=importlib
	@echo "✅ Tests passed"

lint: ## Run linters
	@ruff check packages/*/src/ --output-format=github 2>/dev/null || ruff check packages/*/src/

clean: ## Remove build artifacts
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name node_modules -exec rm -rf {} + 2>/dev/null || true

deploy: ## Deploy to production (blue-green)
	@bash infra/scripts/deploy.sh

rollback: ## Rollback
	@bash infra/scripts/rollback.sh

backup: ## Backup databases
	@bash infra/scripts/backup.sh

health: ## Health check
	@bash infra/scripts/health-check.sh

docker-up: ## Start with Docker (cross-platform)
	docker compose up

docker-down: ## Stop Docker
	docker compose down

docker-build: ## Rebuild Docker images
	docker compose build

version: ## Show version
	@cat VERSION

help: ## Show help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
