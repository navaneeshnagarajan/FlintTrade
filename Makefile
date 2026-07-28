# FlintTrade Makefile
# Usage: make help
#
# ============================================================================
# Shell
# ============================================================================
# This Makefile is the POSIX *alias* surface; scripts/ft.py is the cross-platform
# entry point and is what Windows users run (it needs no shell at all).
#
# GNU Make defaults to /bin/sh, which is dash on Debian/Ubuntu. dash has no
# `set -o pipefail` (the shell errors and aborts the recipe) and its `echo` has
# no `-e` (the escape prefix is printed literally). The retained POSIX recipes
# below — full-check, sync-check, logs-clear, ticks-test — use both, so bash is
# pinned here. Removing this line silently breaks `make full-check` on the
# primary CI/dev platform.
SHELL := /usr/bin/env bash

# ============================================================================
# Platform support
# ============================================================================
# Most recipes are thin delegators to scripts/ft.py, the stdlib-only task runner
# that behaves identically on every OS. If you have no make (or no bash), call
# it directly and get the same behaviour:
#
#   python scripts/ft.py <start|stop|restart|status|dev|setup|test|test-fast|
#                         lint|clean|version|help|desktop-test|desktop-build|
#                         desktop-package|desktop-dev>
#
# After install, the shim makes this available as: flinttrade <same subcommands>
#
# `make` itself needs bash (see the Shell section above) and GNU coreutils, so on
# Windows use scripts/ft.py — or WSL2 if you specifically want make. The grouping
# below is about the underlying WORK, not about where `make` runs:
#
# 1. Works everywhere (Windows 10/11, macOS, Linux)
#    Via scripts/ft.py:
#      setup, start, start-gateway, stop, restart, status, dev, test, test-fast,
#      lint, clean, version, help, desktop-test, desktop-build, desktop-package,
#      desktop-dev
#    Plain Python/uv recipes (no shell builtins):
#      check-python, desktop-icons, update, version-check, audit,
#      broker-sdk-sync, broker-reference-check
#
# 2. POSIX only (the recipe body itself needs bash and GNU coreutils)
#      start-openalgo, start-legacy, health, ticks-test, full-check, sync-check,
#      logs-clear, install-docker, install-server-native, install-native,
#      backup, restore
#
# 3. Needs Docker
#      docker-up, docker-down, docker-build
# ============================================================================

# uv creates .venv/Scripts/python.exe on Windows and .venv/bin/python on POSIX.
# Checking only the POSIX layout is what made `make` fall through to the
# Microsoft Store python3 alias stub (which exits 49 without running anything).
#
# The Windows branch below is for an MSYS/Git-Bash make on Windows (the only way
# to run this Makefile there). Its path is absolute and forward-slashed on
# purpose: an MSYS shell eats the backslashes of a '.venv\Scripts\python.exe',
# and a relative forward-slash command is not resolvable either.
ifeq ($(OS),Windows_NT)
  PYTHON := $(if $(wildcard .venv/Scripts/python.exe),$(CURDIR)/.venv/Scripts/python.exe,python)
else
  PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,$(shell which python3 2>/dev/null || which python 2>/dev/null))
endif
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

# Exported to scripts/ft.py, which reads them from the environment.
OPENALGO_PORT ?= 5000
FLINTTRADE_BACKEND_PORT ?= 5100
FLINTTRADE_BACKEND_HOST ?= 127.0.0.1

.PHONY: setup check-python start start-gateway start-openalgo start-legacy stop restart status test test-fast ticks-test lint clean update dev docker-up docker-down docker-build version version-check health help audit sync-check broker-sdk-sync broker-reference-check full-check install-docker install-native install-server-native backup restore logs-clear desktop-icons desktop-test desktop-build desktop-package desktop-dev

# ======================================================================
# Setup
# ======================================================================

setup: check-python ## First-time setup — install all dependencies
	@"$(PYTHON)" scripts/ft.py setup

# Single-command check: no shell `||`, no subshell, no `echo -e`. sys.exit(str)
# prints to stderr and exits 1, so the message survives whatever shell runs it.
check-python: ## Verify Python >= 3.11 (required for StrEnum)
	@"$(PYTHON)" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 'Error: Python 3.11+ required (StrEnum support). Found: ' + sys.version.split()[0])"

# ======================================================================
# Service management
# ======================================================================

start: ## Start FlintTrade backend API (standalone; OpenAlgo is optional)
	@# delegates: PYTHONPATH=$(FLINTTRADE_PYTHONPATH) $(PYTHON) -m flinttrade_core.app
	@# ft.py joins PYTHONPATH with os.pathsep, so it is ';' on Windows and ':' on POSIX.
	@"$(PYTHON)" scripts/ft.py start

# --- Gateway mode (v0.2.0+) — single process, no separate OpenAlgo ---

start-gateway: start ## Alias for start (standalone FlintTrade backend)

start-openalgo: ## Start optional local OpenAlgo integration service
	@bash infra/scripts/openalgo/start-openalgo.sh

# Legacy mode alias — requires separate OpenAlgo instance
start-legacy: start-openalgo ## Start optional OpenAlgo integration service

stop: ## Stop FlintTrade backend API if it is listening on FLINTTRADE_BACKEND_PORT
	@"$(PYTHON)" scripts/ft.py stop

restart: ## Restart FlintTrade backend
	@"$(PYTHON)" scripts/ft.py restart

status: ## Show service status
	@"$(PYTHON)" scripts/ft.py status

health: ## Run health check
	@FLINTTRADE_HEALTH_STRICT=0 bash infra/scripts/health-check.sh

dev: ## Start terminal dev server + FlintTrade backend
	@# delegates: PYTHONPATH=$(FLINTTRADE_PYTHONPATH) $(PYTHON) -m flinttrade_core.app
	@#            plus the terminal Vite dev server, both supervised by ft.py.
	@"$(PYTHON)" scripts/ft.py dev

# ======================================================================
# Testing and quality
# ======================================================================

test: ## Run all tests (Python + Rust ticks crate)
	@# ft.py expands packages/*/*/tests in Python (no shell glob) and runs the
	@# Rust ticks crate afterwards when cargo is present.
	@"$(PYTHON)" scripts/ft.py test

ticks-test: ## Run the Rust ticks-crate tests (skipped when cargo is absent)
	@# Portable manifest path (cargo accepts forward slashes on Windows too);
	@# guarded on cargo presence so a Python-only contributor's `make test`
	@# does not hard-fail. A real test failure still propagates (no `|| echo`).
	@if command -v cargo >/dev/null 2>&1; then \
		cargo test --manifest-path packages/core/ticks/Cargo.toml; \
	else \
		echo "cargo not found — skipping Rust ticks tests"; \
	fi

test-fast: ## Run tests, stop on first failure
	@"$(PYTHON)" scripts/ft.py test-fast

lint: ## Run linter (ruff)
	@"$(PYTHON)" scripts/ft.py lint

# ======================================================================
# Native desktop app (Electron shell + first-run source bootstrap)
# ======================================================================
# Produces the macOS DMG, Windows NSIS and Linux AppImage shell installers.
# Each target builds for the CURRENT OS/arch; the full cross-platform matrix is
# produced by .github/workflows/desktop-release.yml. See docs/DESKTOP.md.

desktop-icons: ## Regenerate the desktop app icons from the brand mark
	@"$(PYTHON)" packaging/make-icons.py

desktop-test: ## Typecheck and test the Electron shell
	@"$(PYTHON)" scripts/ft.py desktop-test

desktop-build: ## Verify and bundle the Electron shell
	@"$(PYTHON)" scripts/ft.py desktop-build

desktop-package: ## Package and verify the Electron installer for this OS/arch
	@# ft.py builds first, then picks pack:win / pack:mac / pack:linux:x64 /
	@# pack:linux:arm64 from the host OS and architecture.
	@"$(PYTHON)" scripts/ft.py desktop-package

desktop-dev: ## Run the Electron shell against its managed source bootstrap
	@"$(PYTHON)" scripts/ft.py desktop-dev

# ======================================================================
# Maintenance
# ======================================================================

update: ## Update Python dependencies (external test-deps live in .local/external/, update them yourself)
	@# Unquoted, metacharacter-free echoes: plain echo, never echo -e, so the text
	@# is identical whichever POSIX shell ends up running the recipe.
	@echo Updating Python dependencies...
	@# Regenerate the HASHED uv.lock to newest compatible versions, then install
	@# it. Stays inside the SC-07 hash-verified path (never an unhashed
	@# requirements install), which the no-unhashed-install gate now enforces on
	@# this Makefile too.
	@uv lock --upgrade
	@uv sync --frozen --all-packages
	@echo Updated
	@echo Note: external test-deps under .local/external/ are not git submodules anymore.
	@echo Pull updates manually: git -C .local/external/openalgo pull

clean: ## Remove build artifacts (with confirmation)
	@# ft.py deletes the trees with shutil.rmtree (no find/rm -rf).
	@"$(PYTHON)" scripts/ft.py clean

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
	@echo -e "$(YELLOW)--- Version Consistency ---$(RESET)"
	@"$(PYTHON)" scripts/check-version-consistency.py
	@echo -e "$(YELLOW)--- Python Tests ---$(RESET)"
	@set -o pipefail; "$(PYTHON)" -m pytest packages/integrations/gateway/tests/ packages/core/core/tests/ packages/services/screener/tests/ packages/services/engine/tests/ -q --no-header --import-mode=importlib 2>&1 | tail -3
	@echo -e "$(YELLOW)--- Ruff Lint ---$(RESET)"
	@set -o pipefail; "$(PYTHON)" -m ruff check packages/*/*/src/ --statistics 2>&1 | tail -5
	@echo -e "$(YELLOW)--- Terminal ---$(RESET)"
	@cd packages/apps/terminal && set -o pipefail; npm run typecheck 2>&1 | tail -2
	@# Match CI's vitest form: fork-per-file isolation caps peak memory at the
	@# heaviest single file (an unbounded whole-suite run OOMs on TradeIdea).
	@# 8192 MB is the heap even TradeIdea passes at locally (CI has to shard).
	@cd packages/apps/terminal && set -o pipefail; NODE_OPTIONS=--max-old-space-size=8192 npx vitest run --pool=forks --maxWorkers=1 --no-file-parallelism 2>&1 | tail -3
	@echo -e "$(GREEN)=== Done ===$(RESET)"

audit: ## Check repo absorption status
	@"$(PYTHON)" scripts/audit_repos.py

version-check: ## Verify all release-version metadata is aligned
	@"$(PYTHON)" scripts/check-version-consistency.py

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

broker-sdk-sync: ## Refresh repo-local broker SDK refs and fail on upstream drift
	@uv run python scripts/sync_broker_sdk_refs.py --fail-on-drift

broker-reference-check: ## Validate local broker MCP/API reference captures under .local
	@uv run python scripts/check_broker_reference_inventory.py

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

install-server-native: ## Advanced: install FlintTrade as bare-metal Ubuntu/Debian server services
	@bash infra/install/install-native.sh

install-native: install-server-native ## Deprecated alias for install-server-native; desktop app users want desktop-build

backup: ## Run restic backup of FlintTrade data
	@bash infra/backup/backup.sh

restore: ## Restore FlintTrade data from restic backup
	@bash infra/backup/restore.sh

# ======================================================================
# Info
# ======================================================================

version: ## Show version
	@"$(PYTHON)" scripts/ft.py version

help: ## Show this help
	@# ft.py parses the `target: ## description` table out of this Makefile in
	@# Python, replacing the grep|sort|awk pipeline that Windows does not have.
	@"$(PYTHON)" scripts/ft.py help

.DEFAULT_GOAL := help
