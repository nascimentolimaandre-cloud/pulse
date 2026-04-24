#!/usr/bin/env bash
#
# PULSE — post-onboard smoke check
# ---------------------------------------------------------------------------
# Runs AFTER `make onboard`. Validates the stack is actually serving data,
# not just that containers are "up":
#
#   - pulse-api   /health  → 200
#   - pulse-data  /health  → 200
#   - GET /data/v1/metrics/home — has data.deployment_frequency.value
#   - GET /data/v1/pipeline/teams — returns ≥ 10 squads (seed target)
#   - (optional) Vite dev server at :5173 responds — only if running
#
# Philosophy: if this passes, the new dev can open the browser and expect
# a rendered dashboard with KPIs. If this fails, it points at the broken
# layer (db / worker / seed / UI).
#
# Exit: 0 on all-pass, 1 on any hard failure.
# ---------------------------------------------------------------------------

set -uo pipefail

# ---------------------------------------------------------------- colors
if [ -t 1 ]; then
  RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'
  CYN=$'\033[36m'; DIM=$'\033[2m'; BLD=$'\033[1m'; RST=$'\033[0m'
else
  RED=""; GRN=""; YEL=""; CYN=""; DIM=""; BLD=""; RST=""
fi

# ---------------------------------------------------------------- config
API_HOST="${PULSE_API_HOST:-http://localhost:3000}"
DATA_HOST="${PULSE_DATA_HOST:-http://localhost:8000}"
WEB_HOST="${PULSE_WEB_HOST:-http://localhost:5173}"
MIN_SQUADS="${MIN_SQUADS:-10}"

FAILS=0

pass()  { printf "  ${GRN}✓${RST} %-30s ${DIM}%s${RST}\n" "$1" "${2:-}"; }
fail()  { printf "  ${RED}✗${RST} %-30s ${RED}%s${RST}\n" "$1" "$2"
          [ $# -ge 3 ] && printf "    ${DIM}fix: %s${RST}\n" "$3"
          FAILS=$((FAILS + 1)); }
skip()  { printf "  ${YEL}∅${RST} %-30s ${YEL}%s${RST}\n" "$1" "$2"; }
section() { printf "\n${BLD}${CYN}%s${RST}\n" "$1"; }

# http_status URL [timeout_s]
http_status() {
  local url=$1
  local to=${2:-5}
  curl -s -o /dev/null -w "%{http_code}" --max-time "$to" "$url" 2>/dev/null || echo "000"
}

# http_json URL [timeout_s]
http_json() {
  local url=$1
  local to=${2:-10}
  curl -s --max-time "$to" "$url" 2>/dev/null
}

# ---------------------------------------------------------------- header
printf "${BLD}🔍 PULSE verify-dev — post-onboard smoke${RST}\n"
printf "${DIM}(expect all checks ✓ after ${BLD}make onboard${RST}${DIM} completes)${RST}\n"

# ---------------------------------------------------------------- health
section "API health"

# pulse-api uses global prefix `/api/v1` (NestJS setGlobalPrefix).
# Keep the verify path aligned with src/main.ts — if someone changes
# the prefix there, this check will start failing (intentional coupling).
API_HEALTH=$(http_status "$API_HOST/api/v1/health")
if [ "$API_HEALTH" = "200" ]; then
  pass "pulse-api /api/v1/health" "200 OK"
else
  fail "pulse-api /api/v1/health" "HTTP $API_HEALTH" "check logs: docker compose logs pulse-api"
fi

DATA_HEALTH=$(http_status "$DATA_HOST/health")
if [ "$DATA_HEALTH" = "200" ]; then
  pass "pulse-data /health" "200 OK"
else
  fail "pulse-data /health" "HTTP $DATA_HEALTH" "check logs: docker compose logs pulse-data"
fi

# ---------------------------------------------------------------- data content
section "Data content (seed ingested?)"

# /metrics/home — should return DORA metrics with non-null deployment_frequency.
# Timeout is 60s because this endpoint can compute metrics on-demand when a
# snapshot is missing — cold-start after `make seed-dev` may take ~30-60s
# until the metrics-worker fills in snapshots. After seed runs once, the
# response is sub-second.
HOME_RESP=$(http_json "$DATA_HOST/data/v1/metrics/home?period=30d" 60)
if [ -z "$HOME_RESP" ]; then
  fail "GET /metrics/home" "no response (60s timeout)" "pulse-data may be computing snapshots on-demand — wait 60s and retry, or run: docker compose logs metrics-worker"
else
  # Parse with python (always available after doctor passes)
  DF_VALUE=$(printf '%s' "$HOME_RESP" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); v=d.get('data',{}).get('deployment_frequency',{}).get('value'); print(v if v is not None else '')" 2>/dev/null || echo "")
  if [ -z "$DF_VALUE" ] || [ "$DF_VALUE" = "None" ] || [ "$DF_VALUE" = "null" ]; then
    fail "GET /metrics/home" "deployment_frequency is null" "seed didn't run or no deploys were inserted. Run: make seed-dev"
  else
    pass "GET /metrics/home" "deployment_frequency = $DF_VALUE"
  fi
fi

# /pipeline/teams — should return ≥ MIN_SQUADS squads
TEAMS_RESP=$(http_json "$DATA_HOST/data/v1/pipeline/teams" 10)
if [ -z "$TEAMS_RESP" ]; then
  fail "GET /pipeline/teams" "no response" "pulse-data may be still booting — wait 30s and retry"
else
  TEAMS_COUNT=$(printf '%s' "$TEAMS_RESP" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); t=d.get('teams',d) if isinstance(d,dict) else d; print(len(t) if isinstance(t,list) else 0)" 2>/dev/null || echo "0")
  if [ "$TEAMS_COUNT" -ge "$MIN_SQUADS" ]; then
    pass "GET /pipeline/teams" "$TEAMS_COUNT squads (≥ $MIN_SQUADS required)"
  else
    fail "GET /pipeline/teams" "$TEAMS_COUNT squads (< $MIN_SQUADS required)" "seed may be incomplete. Re-run: make seed-reset"
  fi
fi

# ---------------------------------------------------------------- UI (optional)
section "UI (Vite dev server)"

WEB_STATUS=$(http_status "$WEB_HOST" 3)
if [ "$WEB_STATUS" = "200" ]; then
  pass "vite dev server" "200 OK"
elif [ "$WEB_STATUS" = "000" ]; then
  skip "vite dev server" "not running (run: make dev)"
else
  fail "vite dev server" "HTTP $WEB_STATUS" "check: cd packages/pulse-web && npm run dev"
fi

# ---------------------------------------------------------------- summary
printf "\n"
if [ "$FAILS" -eq 0 ]; then
  printf "${GRN}${BLD}✓ Stack is healthy.${RST} ${DIM}Open ${BLD}%s${RST}${DIM} in your browser.${RST}\n" "$WEB_HOST"
  exit 0
else
  printf "${RED}${BLD}✖ %d check(s) failed.${RST} ${DIM}Look at the fix hints above and re-run.${RST}\n" "$FAILS"
  exit 1
fi
