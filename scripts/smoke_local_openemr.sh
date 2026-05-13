#!/usr/bin/env bash
# smoke_local_openemr.sh
# POSIX twin of smoke_local_openemr.ps1. Verifies the local Co-Pilot target
# Docker stack is reachable. Idempotent and read-only — does NOT start
# containers, does NOT seed patients.
#
# Usage:
#   scripts/smoke_local_openemr.sh
#   SKIP_HTTPS_CHECK=1 scripts/smoke_local_openemr.sh
#
# Exits 0 on all-green, 1 on any failure.

set -uo pipefail

TARGET_BASE="${TARGET_BASE_URL:-http://localhost:8300}"
SIDECAR_BASE="${COPILOT_SIDECAR_URL:-http://localhost:8000}"
TIMEOUT="${SMOKE_TIMEOUT_SEC:-5}"

green()  { printf '\033[32m%s\033[0m' "$1"; }
red()    { printf '\033[31m%s\033[0m' "$1"; }
yellow() { printf '\033[33m%s\033[0m' "$1"; }

fail=0

check() {
    local name="$1" url="$2" allow_any="${3:-0}"
    local code
    if ! code=$(curl -k -s -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$url" 2>/dev/null); then
        printf '  %-32s %s  %s\n' "$name" "$(red 'DOWN')" "$url"
        fail=1
        return
    fi
    if [ "$allow_any" = "1" ] || { [ "$code" -ge 200 ] && [ "$code" -lt 500 ]; }; then
        printf '  %-32s %s  %s\n' "$name" "$(green "OK ($code)")" "$url"
    else
        printf '  %-32s %s  %s\n' "$name" "$(red "HTTP $code")" "$url"
        fail=1
    fi
}

echo "AgentForge — local Co-Pilot target smoke check"
echo "  TargetBase  = $TARGET_BASE"
echo "  SidecarBase = $SIDECAR_BASE"
echo ""

check "OpenEMR HTTP login page"     "$TARGET_BASE/interface/login/login.php?site=default" 1
if [ "${SKIP_HTTPS_CHECK:-0}" != "1" ]; then
    check "OpenEMR HTTPS login page"    "https://localhost:9300/interface/login/login.php?site=default" 1
fi
check "Co-Pilot sidecar /healthz"   "$SIDECAR_BASE/healthz" 0
check "phpMyAdmin"                  "http://localhost:8310" 1
check "Mailpit web UI"              "http://localhost:8025" 1

echo ""
if [ "$fail" -ne 0 ]; then
    echo "$(red '[FAIL]') one or more endpoints unreachable."
    echo "$(yellow 'If Docker stack is down, start with:')"
    echo "  cd <openemr-repo> && docker compose -f docker/development-easy/docker-compose.yml up -d"
    echo "$(yellow 'Then start the sidecar separately:')"
    echo "  cd openemr/agent/copilot-api && uvicorn app.main:app --host 0.0.0.0 --port 8000"
    exit 1
fi
echo "$(green '[OK]') All endpoints reachable. Target ready for adversarial runs."
exit 0
