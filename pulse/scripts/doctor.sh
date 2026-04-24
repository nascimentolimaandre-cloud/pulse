#!/usr/bin/env bash
#
# PULSE — dev environment doctor
# ---------------------------------------------------------------------------
# Runs BEFORE docker comes up. Validates the host machine has everything
# needed to bring PULSE online (tools, versions, free ports, disk, memory).
#
# Output: pretty table with ✓ / ✗ / ! markers per check.
# Exit codes:
#   0   all checks pass
#   1   at least one hard-fail — blocks `make onboard`
#   2   only warnings — `make onboard` can proceed, user should address later
#
# Philosophy: every failure prints an actionable fix, never just the symptom.
# Designed for macOS + Linux. WSL2 works; native Windows does not (prints
# a warning suggesting WSL2).
# ---------------------------------------------------------------------------

set -uo pipefail

# ---------------------------------------------------------------- colors
if [ -t 1 ]; then
  RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'
  CYN=$'\033[36m'; DIM=$'\033[2m'; BLD=$'\033[1m'; RST=$'\033[0m'
else
  RED=""; GRN=""; YEL=""; CYN=""; DIM=""; BLD=""; RST=""
fi

# ---------------------------------------------------------------- state
HARD_FAILS=0
WARNINGS=0

pass()  { printf "  ${GRN}✓${RST} %-22s ${DIM}%s${RST}\n" "$1" "${2:-}"; }
fail()  { printf "  ${RED}✗${RST} %-22s ${RED}%s${RST}\n" "$1" "$2"
          [ $# -ge 3 ] && printf "    ${DIM}fix: %s${RST}\n" "$3"
          HARD_FAILS=$((HARD_FAILS + 1)); }
warn()  { printf "  ${YEL}!${RST} %-22s ${YEL}%s${RST}\n" "$1" "$2"
          [ $# -ge 3 ] && printf "    ${DIM}note: %s${RST}\n" "$3"
          WARNINGS=$((WARNINGS + 1)); }
section() { printf "\n${BLD}${CYN}%s${RST}\n" "$1"; }

# ---------------------------------------------------------------- helpers
semver_ge() {
  # returns 0 (true) when $1 >= $2 (major.minor comparison)
  local a b
  a=$(printf '%s' "$1" | awk -F. '{printf "%d%03d", $1, $2}')
  b=$(printf '%s' "$2" | awk -F. '{printf "%d%03d", $1, $2}')
  [ "$a" -ge "$b" ]
}

port_in_use() {
  # Returns 0 if port is in use, 1 if free. Works on macOS + Linux.
  local port=$1
  if command -v lsof >/dev/null 2>&1; then
    lsof -i ":${port}" -sTCP:LISTEN -nP >/dev/null 2>&1
  elif command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :${port}" 2>/dev/null | grep -q ":${port}"
  else
    # Last resort: try to bind — not 100% but better than nothing
    ! (echo > "/dev/tcp/127.0.0.1/${port}") 2>/dev/null
  fi
}

port_owner() {
  local port=$1
  if command -v lsof >/dev/null 2>&1; then
    lsof -i ":${port}" -sTCP:LISTEN -nP 2>/dev/null | awk 'NR==2 {print $1 " (PID " $2 ")"; exit}'
  fi
}

# ---------------------------------------------------------------- header
printf "${BLD}🔍 PULSE doctor — host environment check${RST}\n"
printf "${DIM}(run before ${BLD}make onboard${RST}${DIM} on a fresh clone)${RST}\n"

# ---------------------------------------------------------------- platform
section "Platform"

UNAME_S=$(uname -s)
case "$UNAME_S" in
  Darwin)
    pass "Platform" "macOS ($(uname -m))"
    ;;
  Linux)
    if grep -qi microsoft /proc/version 2>/dev/null; then
      pass "Platform" "WSL2 ($(uname -m))"
    else
      pass "Platform" "Linux ($(uname -m))"
    fi
    ;;
  *)
    warn "Platform" "$UNAME_S" "Native Windows is not supported — use WSL2."
    ;;
esac

# ---------------------------------------------------------------- tools
section "Required tools"

# Bash
if [ -n "${BASH_VERSION:-}" ]; then
  pass "Bash" "$BASH_VERSION"
else
  warn "Bash" "not detected" "doctor.sh runs best under bash; zsh/sh may skip some checks"
fi

# Docker
if ! command -v docker >/dev/null 2>&1; then
  fail "Docker" "not installed" "install from https://docs.docker.com/get-docker/"
elif ! docker info >/dev/null 2>&1; then
  fail "Docker" "daemon not running" "start Docker Desktop (or systemctl start docker)"
else
  DOCKER_VER=$(docker version --format '{{.Client.Version}}' 2>/dev/null || echo unknown)
  if semver_ge "$DOCKER_VER" "24.0"; then
    pass "Docker" "$DOCKER_VER"
  else
    warn "Docker" "$DOCKER_VER (want ≥24.0)" "older Docker may hit compose compat issues"
  fi
fi

# Docker Compose (v2 plugin)
if docker compose version >/dev/null 2>&1; then
  CMP_VER=$(docker compose version --short 2>/dev/null || echo unknown)
  pass "Docker Compose" "v$CMP_VER"
else
  fail "Docker Compose" "v2 plugin missing" "docker CLI 20.10+ ships it, or: https://docs.docker.com/compose/install/"
fi

# Node.js
if ! command -v node >/dev/null 2>&1; then
  fail "Node.js" "not installed" "install via nvm: https://github.com/nvm-sh/nvm  (then: nvm install 20)"
else
  NODE_VER=$(node --version 2>/dev/null | sed 's/^v//')
  if semver_ge "$NODE_VER" "20.0"; then
    pass "Node.js" "$NODE_VER"
  else
    fail "Node.js" "$NODE_VER (want ≥20)" "nvm install 20 && nvm use 20"
  fi
fi

# npm
if command -v npm >/dev/null 2>&1; then
  pass "npm" "$(npm --version)"
else
  fail "npm" "not installed" "bundled with Node.js — reinstall Node"
fi

# Python — host only needs python3 for JSON parsing in verify-dev.sh.
# The real 3.12 runtime lives inside the pulse-data container. A warning
# when host is <3.12 just informs the user that running pytest OUTSIDE
# the container (`cd packages/pulse-data && pytest`) won't work.
if ! command -v python3 >/dev/null 2>&1; then
  fail "Python 3" "not installed" "install Python 3.9+ (host needs it for json parsing). macOS ships 3.9+ by default"
else
  PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
  if semver_ge "$PY_VER" "3.12"; then
    pass "Python 3" "$PY_VER"
  elif semver_ge "$PY_VER" "3.9"; then
    warn "Python 3" "$PY_VER (container uses 3.12)" "host Python is only for JSON parsing; container has its own 3.12. To run pytest on host: pyenv install 3.12"
  else
    fail "Python 3" "$PY_VER (want ≥3.9)" "upgrade Python on host — needed for basic json tooling"
  fi
fi

# Git
if command -v git >/dev/null 2>&1; then
  pass "Git" "$(git --version | awk '{print $3}')"
else
  fail "Git" "not installed" "install git (required for pre-commit hooks)"
fi

# ---------------------------------------------------------------- optional tools
section "Optional tools"

if command -v gitleaks >/dev/null 2>&1; then
  pass "Gitleaks" "$(gitleaks version 2>/dev/null)"
else
  warn "Gitleaks" "not installed" "pre-commit hook will skip secret scan. Install: brew install gitleaks"
fi

if command -v doppler >/dev/null 2>&1; then
  pass "Doppler CLI" "$(doppler --version 2>/dev/null | head -1)"
else
  warn "Doppler CLI" "not installed" "needed ONLY for optional real-ingestion overlay. Install: brew install dopplerhq/cli/doppler"
fi

if command -v gh >/dev/null 2>&1; then
  pass "GitHub CLI" "$(gh --version 2>/dev/null | head -1 | awk '{print $3}')"
else
  warn "GitHub CLI" "not installed" "nice-to-have for PR workflows. Install: brew install gh"
fi

# ---------------------------------------------------------------- ports
section "Ports (must be free)"

# PULSE default ports. If user customized these in .env, doctor will still
# check the defaults — that's fine, it's the onboard-from-clean path.
declare -a PORTS=(
  "3000:pulse-api"
  "5173:pulse-web (Vite)"
  "5432:postgres"
  "6379:redis"
  "8000:pulse-data"
  "9092:kafka"
)

# If docker-compose stack is already up, the ports will be "in use" by
# Docker itself — that's OK, not a conflict. Detect by checking if
# pulse-* containers are running.
STACK_UP=0
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  if docker compose -f docker-compose.yml ps --status running --format '{{.Service}}' 2>/dev/null | grep -q .; then
    STACK_UP=1
  fi
fi

for entry in "${PORTS[@]}"; do
  port="${entry%%:*}"
  label="${entry#*:}"
  if port_in_use "$port"; then
    owner=$(port_owner "$port" || echo "unknown")
    # If stack is already up AND the occupier looks like Docker, this is
    # expected — the ports ARE used, by PULSE itself.
    if [ "$STACK_UP" = "1" ] && printf '%s' "$owner" | grep -qiE 'docke|docker'; then
      pass "Port $port" "$label — bound by running PULSE stack (ok)"
    else
      fail "Port $port ($label)" "in use by $owner" "stop the conflicting service, or change the port in pulse/.env"
    fi
  else
    pass "Port $port" "$label — free"
  fi
done

# ---------------------------------------------------------------- disk + memory
section "Resources"

# Disk
# df works differently on macOS vs Linux; parse available GB either way.
AVAIL_GB=$(df -Pk . | awk 'NR==2 {printf "%d", $4 / 1024 / 1024}')
if [ "$AVAIL_GB" -ge 15 ]; then
  pass "Disk space" "${AVAIL_GB} GB available"
elif [ "$AVAIL_GB" -ge 5 ]; then
  warn "Disk space" "${AVAIL_GB} GB available" "tight — docker images + db may grow to ~10 GB"
else
  fail "Disk space" "${AVAIL_GB} GB available" "free ≥ 15 GB on this partition before continuing"
fi

# Docker memory allocation (best-effort)
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  DOCKER_MEM_BYTES=$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)
  if [ "$DOCKER_MEM_BYTES" -gt 0 ]; then
    DOCKER_MEM_GB=$((DOCKER_MEM_BYTES / 1024 / 1024 / 1024))
    if [ "$DOCKER_MEM_GB" -ge 4 ]; then
      pass "Docker memory" "${DOCKER_MEM_GB} GB allocated"
    else
      warn "Docker memory" "${DOCKER_MEM_GB} GB allocated" "bump Docker Desktop → Settings → Resources → Memory to ≥ 4 GB"
    fi
  fi
fi

# ---------------------------------------------------------------- summary
printf "\n"
if [ "$HARD_FAILS" -gt 0 ]; then
  printf "${RED}${BLD}✖ %d hard fail(s)${RST} ${DIM}+ %d warning(s). Fix and re-run ${BLD}make doctor${RST}${DIM}.${RST}\n" "$HARD_FAILS" "$WARNINGS"
  exit 1
elif [ "$WARNINGS" -gt 0 ]; then
  printf "${YEL}${BLD}⚠ %d warning(s)${RST} ${DIM}— onboard can proceed, address later.${RST}\n" "$WARNINGS"
  exit 2
else
  printf "${GRN}${BLD}✓ All checks passed.${RST} ${DIM}Ready for ${BLD}make onboard${RST}${DIM}.${RST}\n"
  exit 0
fi
