#!/usr/bin/env bash
# FDD-OBS-001 PR 2 — register Datadog credentials live.
#
# Reads DD_API_KEY + DD_APP_KEY + DD_SITE from your shell, calls the
# admin /validate endpoint, prints only safe metadata (status, fingerprint).
# Plaintext keys never touch disk and never echo back from the server.
#
# Usage (run in YOUR terminal, NOT in claude chat):
#   read -s -p "DD API Key: " DD_API_KEY && export DD_API_KEY && echo
#   read -s -p "DD App Key: " DD_APP_KEY && export DD_APP_KEY && echo
#   export DD_SITE=datadoghq.com   # or datadoghq.eu, etc.
#   ./scripts/datadog_register.sh
#
# Add `--no-persist` to do a dry-run (validate without writing to DB).

set -euo pipefail

PULSE_HOST="${PULSE_HOST:-http://localhost:8000}"
PERSIST="true"

if [[ "${1:-}" == "--no-persist" ]]; then
  PERSIST="false"
fi

if [[ -z "${DD_API_KEY:-}" ]]; then
  echo "ERROR: DD_API_KEY not set in your shell." >&2
  echo "Run: read -s -p 'DD API Key: ' DD_API_KEY && export DD_API_KEY && echo" >&2
  exit 1
fi

if [[ -z "${DD_SITE:-}" ]]; then
  echo "DD_SITE not set, defaulting to datadoghq.com" >&2
  DD_SITE="datadoghq.com"
fi

# Build JSON body — keys read from env, NEVER inlined in the script.
# `app_key` is omitted from the body when DD_APP_KEY is unset (the schema
# accepts that — only api_key is required for /validate).
if [[ -n "${DD_APP_KEY:-}" ]]; then
  BODY=$(jq -n \
    --arg ak "$DD_API_KEY" \
    --arg pk "$DD_APP_KEY" \
    --arg site "$DD_SITE" \
    --argjson persist "$PERSIST" \
    '{api_key: $ak, app_key: $pk, site: $site, persist: $persist}')
else
  BODY=$(jq -n \
    --arg ak "$DD_API_KEY" \
    --arg site "$DD_SITE" \
    --argjson persist "$PERSIST" \
    '{api_key: $ak, site: $site, persist: $persist}')
fi

echo "→ POST $PULSE_HOST/data/v1/admin/integrations/datadog/validate"
echo "  site=$DD_SITE  persist=$PERSIST  api_key_prefix=$(echo "$DD_API_KEY" | cut -c1-8)..."

# Capture status code separately so we can distinguish PULSE-side
# rejections (4xx, 5xx) from Datadog-reported invalid (200 + valid:false).
HTTP_CODE=$(curl -sS -o /tmp/_dd_register_resp.json -w "%{http_code}" \
  -X POST "$PULSE_HOST/data/v1/admin/integrations/datadog/validate" \
  -H "Content-Type: application/json" \
  -d "$BODY")
RESPONSE=$(cat /tmp/_dd_register_resp.json)
rm -f /tmp/_dd_register_resp.json

# Pretty-print the response. The server NEVER echoes the api_key back.
echo "$RESPONSE" | jq .

case "$HTTP_CODE" in
  200)
    VALID=$(echo "$RESPONSE" | jq -r '.valid // false')
    PERSISTED=$(echo "$RESPONSE" | jq -r '.persisted // false')
    if [[ "$VALID" == "true" ]]; then
      echo "✓ Datadog accepted the credential."
      [[ "$PERSISTED" == "true" ]] && \
        echo "✓ Encrypted credential stored in tenant_observability_credentials."
      exit 0
    else
      echo "✗ Datadog rejected the API key/app key/site combination." >&2
      echo "  Verify: 1) API key value 2) Application Key permissions 3) site matches your DD region." >&2
      exit 2
    fi
    ;;
  422)
    echo "✗ PULSE schema validation rejected the request (Layer 1 SSRF defense)." >&2
    echo "  Most common cause: DD_SITE includes your org subdomain. Use the BASE site only:" >&2
    echo "    UI url 'webmotors.datadoghq.com'   → DD_SITE=datadoghq.com" >&2
    echo "    UI url 'acme.us5.datadoghq.com'    → DD_SITE=us5.datadoghq.com" >&2
    echo "    UI url 'acme.datadoghq.eu'         → DD_SITE=datadoghq.eu" >&2
    exit 3
    ;;
  503)
    echo "✗ PULSE could not complete the request (network/master-key issue)." >&2
    echo "  Check: 1) PULSE_OBS_MASTER_KEY set in .env 2) pulse-data can reach api.\$DD_SITE" >&2
    exit 4
    ;;
  *)
    echo "✗ Unexpected HTTP $HTTP_CODE from PULSE." >&2
    exit 5
    ;;
esac
