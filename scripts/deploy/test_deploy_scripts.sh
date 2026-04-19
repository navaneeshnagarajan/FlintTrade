#!/usr/bin/env bash
# Tests for FlintTrade deploy scripts — dry-run validation only.
#
# Usage:
#   bash test_deploy_scripts.sh
#
# What this tests:
#   - All three scripts are syntactically valid (bash -n)
#   - All three scripts accept --dry-run without crashing
#   - All three scripts accept --help without crashing
#   - Service file templates contain required placeholders
#   - Nginx template contains required proxy directives
#
# Exit code: 0 if all tests pass, 1 if any fail.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

_red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
_green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
_blue()  { printf '\033[0;34m%s\033[0m\n' "$*"; }

PASS=0
FAIL=0

assert_pass() {
    local desc="$1"
    shift
    if "$@" 2>/dev/null; then
        _green "[PASS] $desc"
        ((PASS++))
    else
        _red   "[FAIL] $desc"
        ((FAIL++))
    fi
}

assert_file_contains() {
    local file="$1"
    local pattern="$2"
    local desc="${3:-$file contains: $pattern}"
    if grep -qF "$pattern" "$file" 2>/dev/null; then
        _green "[PASS] $desc"
        ((PASS++))
    else
        _red   "[FAIL] $desc"
        ((FAIL++))
    fi
}

assert_file_exists() {
    local file="$1"
    local desc="File exists: $file"
    if [[ -f "$file" ]]; then
        _green "[PASS] $desc"
        ((PASS++))
    else
        _red   "[FAIL] $desc"
        ((FAIL++))
    fi
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

test_file_existence() {
    _blue "--- File existence ---"
    assert_file_exists "$SCRIPT_DIR/install.sh"
    assert_file_exists "$SCRIPT_DIR/update.sh"
    assert_file_exists "$SCRIPT_DIR/uninstall.sh"
    assert_file_exists "$SCRIPT_DIR/flinttrade.service"
    assert_file_exists "$SCRIPT_DIR/flinttrade-terminal.service"
    assert_file_exists "$SCRIPT_DIR/nginx.conf.template"
}

test_bash_syntax() {
    _blue "--- Bash syntax (bash -n) ---"
    assert_pass "install.sh syntax valid"    bash -n "$SCRIPT_DIR/install.sh"
    assert_pass "update.sh syntax valid"     bash -n "$SCRIPT_DIR/update.sh"
    assert_pass "uninstall.sh syntax valid"  bash -n "$SCRIPT_DIR/uninstall.sh"
    assert_pass "test script syntax valid"   bash -n "$SCRIPT_DIR/test_deploy_scripts.sh"
}

test_help_flags() {
    _blue "--- --help flags ---"
    assert_pass "install.sh --help exits 0"    bash "$SCRIPT_DIR/install.sh"   --help
    assert_pass "update.sh --help exits 0"     bash "$SCRIPT_DIR/update.sh"    --help
    assert_pass "uninstall.sh --help exits 0"  bash "$SCRIPT_DIR/uninstall.sh" --help
}

test_dry_run_install() {
    _blue "--- install.sh --dry-run ---"
    # Capture output; script must exit 0 in dry-run on any machine.
    # We set INSTALL_DIR to a temp path so no real paths are needed.
    local tmpdir
    tmpdir="$(mktemp -d)"
    trap 'rm -rf "$tmpdir"' RETURN

    # Fake a git repo in tmpdir so the "already exists" branch is taken
    git init "$tmpdir" --quiet
    touch "$tmpdir/.env.example"

    local output
    output=$(
        INSTALL_DIR="$tmpdir" \
        bash "$SCRIPT_DIR/install.sh" --dry-run 2>&1
    ) && exit_code=0 || exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
        _green "[PASS] install.sh --dry-run exits 0"
        ((PASS++))
    else
        _red   "[FAIL] install.sh --dry-run exited $exit_code"
        ((FAIL++))
    fi

    if echo "$output" | grep -q "DRY-RUN"; then
        _green "[PASS] install.sh --dry-run prints DRY-RUN messages"
        ((PASS++))
    else
        _red   "[FAIL] install.sh --dry-run does not print DRY-RUN messages"
        ((FAIL++))
    fi
}

test_dry_run_update() {
    _blue "--- update.sh --dry-run ---"
    local tmpdir
    tmpdir="$(mktemp -d)"
    trap 'rm -rf "$tmpdir"' RETURN

    git init "$tmpdir" --quiet

    local output
    output=$(
        INSTALL_DIR="$tmpdir" \
        bash "$SCRIPT_DIR/update.sh" --dry-run 2>&1
    ) && exit_code=0 || exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
        _green "[PASS] update.sh --dry-run exits 0"
        ((PASS++))
    else
        _red   "[FAIL] update.sh --dry-run exited $exit_code"
        ((FAIL++))
    fi

    if echo "$output" | grep -q "DRY-RUN"; then
        _green "[PASS] update.sh --dry-run prints DRY-RUN messages"
        ((PASS++))
    else
        _red   "[FAIL] update.sh --dry-run does not print DRY-RUN messages"
        ((FAIL++))
    fi
}

test_dry_run_uninstall() {
    _blue "--- uninstall.sh --dry-run ---"
    local tmpdir
    tmpdir="$(mktemp -d)"
    trap 'rm -rf "$tmpdir"' RETURN

    local output
    output=$(
        INSTALL_DIR="$tmpdir" \
        bash "$SCRIPT_DIR/uninstall.sh" --dry-run 2>&1
    ) && exit_code=0 || exit_code=$?

    if [[ $exit_code -eq 0 ]]; then
        _green "[PASS] uninstall.sh --dry-run exits 0"
        ((PASS++))
    else
        _red   "[FAIL] uninstall.sh --dry-run exited $exit_code"
        ((FAIL++))
    fi

    if echo "$output" | grep -q "DRY-RUN"; then
        _green "[PASS] uninstall.sh --dry-run prints DRY-RUN messages"
        ((PASS++))
    else
        _red   "[FAIL] uninstall.sh --dry-run does not print DRY-RUN messages"
        ((FAIL++))
    fi
}

test_service_templates() {
    _blue "--- systemd service templates ---"
    local backend="$SCRIPT_DIR/flinttrade.service"
    local terminal="$SCRIPT_DIR/flinttrade-terminal.service"

    assert_file_contains "$backend"  "{{INSTALL_DIR}}"       "backend: {{INSTALL_DIR}} placeholder"
    assert_file_contains "$backend"  "{{FLINTTRADE_USER}}"   "backend: {{FLINTTRADE_USER}} placeholder"
    assert_file_contains "$backend"  "{{BACKEND_PORT}}"      "backend: {{BACKEND_PORT}} placeholder"
    assert_file_contains "$backend"  "Restart=on-failure"    "backend: Restart=on-failure"
    assert_file_contains "$backend"  "EnvironmentFile="      "backend: EnvironmentFile directive"
    assert_file_contains "$backend"  "NoNewPrivileges=true"  "backend: security hardening"

    assert_file_contains "$terminal" "{{INSTALL_DIR}}"       "terminal: {{INSTALL_DIR}} placeholder"
    assert_file_contains "$terminal" "{{FLINTTRADE_USER}}"   "terminal: {{FLINTTRADE_USER}} placeholder"
    assert_file_contains "$terminal" "{{TERMINAL_PORT}}"     "terminal: {{TERMINAL_PORT}} placeholder"
    assert_file_contains "$terminal" "Restart=on-failure"    "terminal: Restart=on-failure"
}

test_nginx_template() {
    _blue "--- nginx.conf.template ---"
    local nginx="$SCRIPT_DIR/nginx.conf.template"

    assert_file_contains "$nginx" "{{TERMINAL_PORT}}"       "nginx: {{TERMINAL_PORT}} placeholder"
    assert_file_contains "$nginx" "{{BACKEND_PORT}}"        "nginx: {{BACKEND_PORT}} placeholder"
    assert_file_contains "$nginx" "proxy_pass"              "nginx: proxy_pass directive"
    assert_file_contains "$nginx" "/ft-api/"                "nginx: FlintTrade backend route"
    assert_file_contains "$nginx" "/api/"                   "nginx: OpenAlgo API route"
    assert_file_contains "$nginx" "Upgrade"                 "nginx: WebSocket upgrade support"
    assert_file_contains "$nginx" "gzip on"                 "nginx: compression enabled"
    assert_file_contains "$nginx" "X-Frame-Options"         "nginx: security headers"
}

test_idempotency_markers() {
    _blue "--- Idempotency checks ---"
    # Check that scripts test for existing state before acting
    assert_file_contains "$SCRIPT_DIR/install.sh"   "already"  "install.sh checks for existing state"
    assert_file_contains "$SCRIPT_DIR/uninstall.sh" "not found" "uninstall.sh handles missing state"
    assert_file_contains "$SCRIPT_DIR/update.sh"    "is-active" "update.sh checks service state"
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

main() {
    _blue "======================================================"
    _blue " FlintTrade Deploy Scripts — Test Suite"
    _blue "======================================================"
    echo ""

    test_file_existence
    test_bash_syntax
    test_help_flags
    test_dry_run_install
    test_dry_run_update
    test_dry_run_uninstall
    test_service_templates
    test_nginx_template
    test_idempotency_markers

    echo ""
    _blue "======================================================"
    echo "  Passed: $PASS"
    if [[ $FAIL -gt 0 ]]; then
        _red "  Failed: $FAIL"
        echo ""
        exit 1
    else
        _green "  Failed: $FAIL"
        _green " All tests passed!"
    fi
}

main "$@"
