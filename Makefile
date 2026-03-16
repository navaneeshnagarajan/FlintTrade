.PHONY: setup start stop update test lint clean deploy rollback backup health help

setup: ## First-time setup — clones OpenAlgo, installs all deps
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

version: ## Show version
	@cat VERSION

help: ## Show help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
