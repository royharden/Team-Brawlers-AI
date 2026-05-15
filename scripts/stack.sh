#!/usr/bin/env bash
# stack.sh -- one controller for the full local AgentForge stack.
#
# Bash / WSL parity of stack.ps1. Start / stop / restart / check status of all
# three layers or any subset. Run with no arguments for an interactive wizard.
#
# Layers (dependency order):
#   target      OpenEMR Clinical Co-Pilot host  -- docker compose (EMR-SO)
#   sidecar     Co-Pilot FastAPI sidecar        -- python -m uvicorn, port 8000
#   agentforge  AgentForge platform (API + UI)  -- docker compose (this repo)
#
# `up` starts selected layers target->sidecar->agentforge; `down` stops them in
# reverse; `restart` does both. Every operation is idempotent.
#
# CRITICAL: teardown never passes -v to docker compose down. OpenEMR patient-DB
# volumes and the AgentForge SQLite volume always survive.
#
# Usage:
#   ./scripts/stack.sh                          # interactive wizard
#   ./scripts/stack.sh status                   # status of all three
#   ./scripts/stack.sh status target            # status of one layer
#   ./scripts/stack.sh up                       # start everything (cold: slow)
#   ./scripts/stack.sh up sidecar agentforge    # start just the fast layers
#   ./scripts/stack.sh down                     # stop everything
#   ./scripts/stack.sh down agentforge          # stop just AgentForge
#   ./scripts/stack.sh restart sidecar          # bounce the sidecar
#   BUILD=1 ./scripts/stack.sh up agentforge    # rebuild + start AgentForge
#
# Env overrides:
#   EMR_SO_ROOT, SIDECAR_PYTHON, TIMEOUT_SEC (180), TARGET_TIMEOUT_SEC (1500), BUILD
#
# ROUTINE WORKFLOW: leave the heavy OpenEMR target up for days; cycle only the
# fast layers --  ./scripts/stack.sh restart sidecar agentforge
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
STACK_DIR="$REPO_ROOT/.stack"
AGENTFORGE_COMPOSE="$REPO_ROOT/docker-compose.local.yml"
SIDECAR_PID_FILE="$STACK_DIR/sidecar.pid"
SIDECAR_LOG="$STACK_DIR/sidecar.log"

EMR_SO_ROOT="${EMR_SO_ROOT:-$(cd "$REPO_ROOT/../.." && pwd)/EMR-SO}"
TARGET_COMPOSE_DIR="$EMR_SO_ROOT/openemr/docker/development-easy"
TARGET_COMPOSE_BASE="$TARGET_COMPOSE_DIR/docker-compose.yml"
TARGET_COMPOSE_OVERRIDE="$TARGET_COMPOSE_DIR/docker-compose.override.yml"
SIDECAR_DIR="$EMR_SO_ROOT/openemr/agent/copilot-api"

# The target needs BOTH compose files. docker-compose.override.yml injects the
# COPILOT_* env vars (sidecar URL, gateway shared secret, demo-mode flags) into
# the openemr container -- without them the PHP gateway can't reach the sidecar.
# Passing -f explicitly suppresses Compose's automatic override merge, so the
# override MUST be named explicitly too.
TARGET_COMPOSE_ARGS=(-f "$TARGET_COMPOSE_BASE")
if [ -f "$TARGET_COMPOSE_OVERRIDE" ]; then
  TARGET_COMPOSE_ARGS+=(-f "$TARGET_COMPOSE_OVERRIDE")
fi
SIDECAR_PYTHON="${SIDECAR_PYTHON:-python3}"
TIMEOUT_SEC="${TIMEOUT_SEC:-180}"
TARGET_TIMEOUT_SEC="${TARGET_TIMEOUT_SEC:-1500}"
BUILD="${BUILD:-0}"
TARGET_CONTAINER="development-easy-openemr-1"
CANONICAL=(target sidecar agentforge)

mkdir -p "$STACK_DIR"

# --- generic helpers ------------------------------------------------------
http_ok() {
  local url="$1"
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' -m 4 "$url" 2>/dev/null || echo 000)"
  [ "$code" != "000" ]
}

wait_http() {
  local name="$1" url="$2" timeout="$3"
  printf '  waiting for %s (%s) ...' "$name" "$url"
  local deadline=$(( $(date +%s) + timeout ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    if http_ok "$url"; then echo " OK"; return 0; fi
    sleep 2; printf '.'
  done
  echo " TIMEOUT"; return 1
}

container_health() {
  # echoes: healthy | unhealthy | starting | nohealthcheck | running | absent
  local c="$1" state health
  state="$(docker inspect --format '{{.State.Status}}' "$c" 2>/dev/null || echo '')"
  if [ -z "$state" ] || [ "$state" != "running" ]; then echo "absent"; return; fi
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}nohealthcheck{{end}}' "$c" 2>/dev/null || echo nohealthcheck)"
  echo "$health"
}

wait_container_healthy() {
  local name="$1" container="$2" timeout="$3"
  printf '  waiting for %s healthcheck (%s) ...' "$name" "$container"
  local deadline=$(( $(date +%s) + timeout ))
  while [ "$(date +%s)" -lt "$deadline" ]; do
    local h; h="$(container_health "$container")"
    if [ "$h" = "healthy" ]; then echo " OK"; return 0; fi
    if [ "$h" = "nohealthcheck" ] || [ "$h" = "running" ]; then
      echo " (no healthcheck -- assuming up)"; return 0
    fi
    sleep 5; printf '.'
  done
  echo " TIMEOUT"; return 1
}

# --- status ---------------------------------------------------------------
# Sets globals LAYER_STATE / LAYER_DETAIL for the given layer.
layer_status() {
  local layer="$1"
  case "$layer" in
    target)
      local h; h="$(container_health "$TARGET_CONTAINER")"
      case "$h" in
        healthy)               LAYER_STATE="UP";       LAYER_DETAIL="container healthy, http://localhost:8300" ;;
        starting|unhealthy)    LAYER_STATE="STARTING"; LAYER_DETAIL="cold boot in progress (rsync) -- can take 15-25 min" ;;
        running|nohealthcheck) LAYER_STATE="UP";       LAYER_DETAIL="container running (no healthcheck)" ;;
        *)                     LAYER_STATE="DOWN";     LAYER_DETAIL="container not running" ;;
      esac ;;
    sidecar)
      if http_ok "http://localhost:8000/healthz"; then
        LAYER_STATE="UP"; LAYER_DETAIL="http://localhost:8000/healthz responding"
      else
        local note=""
        [ -f "$SIDECAR_PID_FILE" ] && note=" (stale pidfile $(cat "$SIDECAR_PID_FILE" 2>/dev/null))"
        LAYER_STATE="DOWN"; LAYER_DETAIL="not responding on :8000${note}"
      fi ;;
    agentforge)
      # Container-authoritative: a port squatter (e.g. a stale non-Docker
      # uvicorn on 127.0.0.1:8100) must NOT read as "up". The HTTP probe only
      # counts when the matching container is actually running.
      local api_state ui_state api_running=0 ui_running=0 api_up=0 ui_up=0
      api_state="$(docker inspect --format '{{.State.Status}}' agentforge-api 2>/dev/null || echo '')"
      ui_state="$(docker inspect --format '{{.State.Status}}' agentforge-ui 2>/dev/null || echo '')"
      [ "$api_state" = "running" ] && api_running=1
      [ "$ui_state" = "running" ] && ui_running=1
      if [ "$api_running" -eq 0 ] && [ "$ui_running" -eq 0 ]; then
        LAYER_STATE="DOWN"; LAYER_DETAIL="API + UI containers not running"
      else
        [ "$api_running" -eq 1 ] && http_ok "http://localhost:8100/healthz" && api_up=1
        [ "$ui_running" -eq 1 ]  && http_ok "http://localhost:8501"         && ui_up=1
        if [ "$api_up" -eq 1 ] && [ "$ui_up" -eq 1 ]; then
          LAYER_STATE="UP"; LAYER_DETAIL="API :8100 + UI :8501 responding"
        else
          local a u
          if [ "$api_running" -eq 1 ]; then
            [ "$api_up" -eq 1 ] && a="API up" || a="API container running, not ready"
          else a="API down"; fi
          if [ "$ui_running" -eq 1 ]; then
            [ "$ui_up" -eq 1 ] && u="UI up" || u="UI container running, not ready"
          else u="UI down"; fi
          LAYER_STATE="PARTIAL"; LAYER_DETAIL="$a, $u"
        fi
      fi ;;
    *) LAYER_STATE="?"; LAYER_DETAIL="unknown layer" ;;
  esac
}

show_status() {
  echo ""
  echo "  Layer        State      Detail"
  echo "  -----------  ---------  ---------------------------------------------"
  for l in "$@"; do
    layer_status "$l"
    printf '  %-11s  %-9s  %s\n' "$l" "$LAYER_STATE" "$LAYER_DETAIL"
  done
  echo ""
}

# --- per-layer start ------------------------------------------------------
start_target() {
  echo "[target] OpenEMR"
  [ -f "$TARGET_COMPOSE_BASE" ] || { echo "  ERROR: target compose not found: $TARGET_COMPOSE_BASE"; return 1; }
  if [ ! -f "$TARGET_COMPOSE_OVERRIDE" ]; then
    echo "  WARNING: override not found ($TARGET_COMPOSE_OVERRIDE) --"
    echo "           openemr will start WITHOUT the COPILOT_* env vars."
  fi
  # Always run `docker compose up -d` with both files. It is idempotent: a
  # near-instant no-op when the container already matches the desired config,
  # a recreate when config drifted (e.g. the override was missing before).
  docker compose "${TARGET_COMPOSE_ARGS[@]}" up -d || { echo "  ERROR: docker compose up failed"; return 1; }
  # If the container is still healthy a beat after `up -d`, it was a no-op.
  # Otherwise a recreate kicked off a cold boot -- warn about the duration.
  sleep 2
  if [ "$(container_health "$TARGET_CONTAINER")" != "healthy" ]; then
    echo "  NOTE: recreate triggered a cold boot -- rsync of the OneDrive-backed"
    echo "        repo into the container routinely takes 15-25 min. Be patient."
  fi
  wait_container_healthy "OpenEMR" "$TARGET_CONTAINER" "$TARGET_TIMEOUT_SEC"
}

start_sidecar() {
  echo "[sidecar] Co-Pilot"
  if http_ok "http://localhost:8000/healthz"; then echo "  already up -- leaving it alone"; return 0; fi
  [ -d "$SIDECAR_DIR" ] || { echo "  ERROR: sidecar dir not found: $SIDECAR_DIR"; return 1; }
  echo "  launching: $SIDECAR_PYTHON -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
  ( cd "$SIDECAR_DIR" && nohup "$SIDECAR_PYTHON" -m uvicorn app.main:app \
      --host 127.0.0.1 --port 8000 > "$SIDECAR_LOG" 2>&1 & echo $! > "$SIDECAR_PID_FILE" )
  echo "  sidecar PID $(cat "$SIDECAR_PID_FILE") -> $SIDECAR_PID_FILE"
  if ! wait_http "sidecar /healthz" "http://localhost:8000/healthz" "$TIMEOUT_SEC"; then
    echo "  last 20 lines of $SIDECAR_LOG:"; tail -n 20 "$SIDECAR_LOG" 2>/dev/null || true
    return 1
  fi
}

start_agentforge() {
  echo "[agentforge] platform"
  [ -f "$AGENTFORGE_COMPOSE" ] || { echo "  ERROR: compose not found: $AGENTFORGE_COMPOSE"; return 1; }
  if [ "$BUILD" = "1" ]; then
    echo "  building image (BUILD=1) ..."
    docker compose -f "$AGENTFORGE_COMPOSE" build || { echo "  ERROR: build failed"; return 1; }
  fi
  docker compose -f "$AGENTFORGE_COMPOSE" up -d || { echo "  ERROR: docker compose up failed"; return 1; }
  local ok=0
  wait_http "AgentForge API /healthz" "http://localhost:8100/healthz" "$TIMEOUT_SEC" || ok=1
  wait_http "AgentForge UI" "http://localhost:8501" 60 || true
  return "$ok"
}

# --- per-layer stop -------------------------------------------------------
stop_target() {
  echo "[target] OpenEMR"
  [ -f "$TARGET_COMPOSE_BASE" ] || { echo "  compose not found -- skipping"; return 0; }
  # Pass both files on `down` too so Compose resolves the same project/config
  # it was brought up with. NO -v -- patient DB + site volumes survive.
  docker compose "${TARGET_COMPOSE_ARGS[@]}" down && echo "  stopped" \
    || echo "  docker compose down had a non-zero exit"
}

stop_sidecar() {
  echo "[sidecar] Co-Pilot"
  local stopped=0
  if [ -f "$SIDECAR_PID_FILE" ]; then
    local pid; pid="$(tr -dc '0-9' < "$SIDECAR_PID_FILE" || true)"
    if [ -n "$pid" ]; then
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        echo "  stopped sidecar PID $pid (from pidfile)"
      else
        echo "  pidfile PID $pid not running (already gone)"
      fi
      stopped=1
    fi
    rm -f "$SIDECAR_PID_FILE"
  fi
  if [ "$stopped" -eq 0 ]; then
    local pid8000; pid8000="$(lsof -ti :8000 2>/dev/null | head -n1 || true)"
    if [ -n "$pid8000" ]; then
      echo "  no pidfile; :8000 owned by PID $pid8000 -- stopping it"
      kill "$pid8000" 2>/dev/null || true
      echo "  stopped"
    else
      echo "  nothing listening on :8000 -- already down"
    fi
  fi
}

stop_agentforge() {
  echo "[agentforge] platform"
  [ -f "$AGENTFORGE_COMPOSE" ] || { echo "  compose not found -- skipping"; return 0; }
  docker compose -f "$AGENTFORGE_COMPOSE" down && echo "  stopped" \
    || echo "  docker compose down had a non-zero exit"
}

# --- orchestration --------------------------------------------------------
resolve_layers() {
  # echoes space-separated canonical layer list for the given raw args
  local raw=("$@")
  if [ "${#raw[@]}" -eq 0 ]; then echo "${CANONICAL[@]}"; return; fi
  local want_target=0 want_sidecar=0 want_af=0
  for r in "${raw[@]}"; do
    case "$(echo "$r" | tr '[:upper:]' '[:lower:]')" in
      all)                     echo "${CANONICAL[@]}"; return ;;
      target|openemr)          want_target=1 ;;
      sidecar|copilot)         want_sidecar=1 ;;
      agentforge|af|platform)  want_af=1 ;;
      *) echo "  WARNING: unknown layer '$r' ignored" >&2 ;;
    esac
  done
  local out=()
  [ "$want_target" -eq 1 ]  && out+=(target)
  [ "$want_sidecar" -eq 1 ] && out+=(sidecar)
  [ "$want_af" -eq 1 ]      && out+=(agentforge)
  if [ "${#out[@]}" -eq 0 ]; then echo "${CANONICAL[@]}"; else echo "${out[@]}"; fi
}

invoke_up() {
  for l in "$@"; do          # canonical order
    case "$l" in
      target)     start_target     || { echo ""; echo "[FAIL] layer 'target' did not come up."; return 1; } ;;
      sidecar)    start_sidecar    || { echo ""; echo "[FAIL] layer 'sidecar' did not come up."; return 1; } ;;
      agentforge) start_agentforge || { echo ""; echo "[FAIL] layer 'agentforge' did not come up."; return 1; } ;;
    esac
  done
}

invoke_down() {
  # reverse the argument list
  local rev=() i
  for (( i=$#; i>=1; i-- )); do rev+=("${!i}"); done
  for l in "${rev[@]}"; do
    case "$l" in
      target)     stop_target ;;
      sidecar)    stop_sidecar ;;
      agentforge) stop_agentforge ;;
    esac
  done
}

invoke_action() {
  local act="$1"; shift
  local sel=("$@")
  case "$act" in
    up)
      echo "AgentForge stack -- UP  [${sel[*]}]"; echo ""
      if invoke_up "${sel[@]}"; then echo ""; echo "[OK] requested layers are up."; fi
      show_status "${CANONICAL[@]}" ;;
    down)
      echo "AgentForge stack -- DOWN  [${sel[*]}]"; echo ""
      invoke_down "${sel[@]}"
      echo ""; echo "[OK] requested layers are down. Docker volumes preserved (no -v)."
      show_status "${CANONICAL[@]}" ;;
    restart)
      echo "AgentForge stack -- RESTART  [${sel[*]}]"; echo ""
      invoke_down "${sel[@]}"; echo ""
      if invoke_up "${sel[@]}"; then echo ""; echo "[OK] requested layers restarted."; fi
      show_status "${CANONICAL[@]}" ;;
    status)
      echo "AgentForge stack -- STATUS"
      show_status "${sel[@]}" ;;
    *)
      echo "Unknown action: $act" >&2
      echo "Valid actions: up | down | restart | status   (or run with no args for the wizard)" >&2
      return 2 ;;
  esac
}

# --- wizard ---------------------------------------------------------------
read_layer_selection() {
  # echoes canonical layer list based on interactive input; empty on none
  echo "" >&2
  echo "  Which layer(s)? Enter numbers comma-separated (e.g. 2,3), or A for all:" >&2
  echo "    1) target      (OpenEMR  -- SLOW to cold-start, 15-25 min)" >&2
  echo "    2) sidecar     (Co-Pilot -- seconds)" >&2
  echo "    3) agentforge  (platform -- seconds)" >&2
  printf '  > ' >&2
  local raw; read -r raw
  if [[ "$raw" =~ ^[[:space:]]*[Aa][[:space:]]*$ ]]; then echo "${CANONICAL[@]}"; return; fi
  local want_target=0 want_sidecar=0 want_af=0
  IFS=',' read -ra toks <<< "$raw"
  for t in "${toks[@]}"; do
    case "$(echo "$t" | tr -d '[:space:]')" in
      1) want_target=1 ;;
      2) want_sidecar=1 ;;
      3) want_af=1 ;;
      "") ;;
      *) echo "  (ignored: '$t')" >&2 ;;
    esac
  done
  local out=()
  [ "$want_target" -eq 1 ]  && out+=(target)
  [ "$want_sidecar" -eq 1 ] && out+=(sidecar)
  [ "$want_af" -eq 1 ]      && out+=(agentforge)
  echo "${out[@]}"
}

show_wizard() {
  while true; do
    clear 2>/dev/null || true
    echo "=============================================="
    echo "  AgentForge Stack Control"
    echo "=============================================="
    show_status "${CANONICAL[@]}"
    echo "  What would you like to do?"
    echo "    1) Start   all layers"
    echo "    2) Stop    all layers"
    echo "    3) Restart all layers"
    echo "    4) Start   specific layer(s)"
    echo "    5) Stop    specific layer(s)"
    echo "    6) Restart specific layer(s)"
    echo "    7) Refresh status"
    echo "    Q) Quit"
    echo ""
    printf '  Choice: '
    local choice; read -r choice
    local act="" sel=()
    case "$(echo "$choice" | tr '[:lower:]' '[:upper:]' | tr -d '[:space:]')" in
      1) act="up";      sel=("${CANONICAL[@]}") ;;
      2) act="down";    sel=("${CANONICAL[@]}") ;;
      3) act="restart"; sel=("${CANONICAL[@]}") ;;
      4) act="up";      read -ra sel <<< "$(read_layer_selection)" ;;
      5) act="down";    read -ra sel <<< "$(read_layer_selection)" ;;
      6) act="restart"; read -ra sel <<< "$(read_layer_selection)" ;;
      7) continue ;;
      Q) echo ""; echo "  bye."; return ;;
      *) echo "  (unrecognized choice)"; sleep 1; continue ;;
    esac
    if [ "${#sel[@]}" -gt 0 ]; then
      echo ""
      invoke_action "$act" "${sel[@]}"
    else
      echo "  nothing selected."
    fi
    echo ""
    printf '  press Enter to return to the menu '; read -r _
  done
}

# --- entry point ----------------------------------------------------------
ACTION="${1:-}"
if [ -z "$ACTION" ] || [ "$ACTION" = "wizard" ]; then
  show_wizard
  exit 0
fi
shift || true
read -ra SELECTED <<< "$(resolve_layers "$@")"
invoke_action "$ACTION" "${SELECTED[@]}"
