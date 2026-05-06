# ADR-021: Per-tenant Observability Credentials Storage

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** Main session (orchestrator) + `pulse-data-engineer` + `pulse-ciso` (review pending)
- **Related:** ADR-002 (RLS multi-tenancy), ADR-011 (metadata-only security), ADR-014 (Jira discovery — same per-tenant pattern), FDD-OBS-001

---

## Context

PULSE Signals (FDD-OBS-001) introduces integration with **Datadog** (R2),
**New Relic** (R3), and **Grafana / Honeycomb / Dynatrace** (R4). Each
tenant brings their **own credentials**:

- **Datadog**: API key + Application key (no OAuth for customer apps).
- **New Relic**: User key (single key, per-organization).
- **Grafana**: instance URL + service account token.

Today, PULSE stores integration credentials for Jira / GitHub / Jenkins
in **environment variables** (`.env`) — single-tenant only. Observability
credentials cannot follow this pattern: SaaS tenants must self-serve
credential management, rotation must work without service restart, and
each tenant's secrets must be isolated.

Two storage options:

| Option | Pros | Cons |
|--------|------|------|
| **A — AWS Secrets Manager** | HSM-backed, KMS encryption, AWS-native rotation, audit log | $0.40/secret/month + $0.05/10k API calls; ~50ms cold-start fetch tax per worker poll; LocalStack overhead in dev; 100 tenants × 3 providers ≈ $144/yr baseline |
| **B — Postgres column with `pgcrypto`** | Zero new infra; mirrors existing `tenant_jira_config` pattern; no extra fetch latency; trivial local dev | Encryption key (master) lives in env var; key rotation is operational toil at scale (>500 tenants) |

## Decision

**Adopt Option B** for R2-R3 (`tenant_observability_credentials` table
with `pgp_sym_encrypt` from `pgcrypto`). Migrate to AWS Secrets Manager
in R4 when (a) we onboard a regulated tenant requiring HSM-backed keys,
or (b) we cross ~500 tenants where pgcrypto rotation cost exceeds
$0.40/mo/tenant.

### Schema (migration `016_observability_credentials`)

```sql
CREATE TABLE tenant_observability_credentials (
    tenant_id           UUID NOT NULL,
    provider            TEXT NOT NULL CHECK (provider IN
                            ('datadog','newrelic','grafana','honeycomb','dynatrace')),
    api_key_encrypted   BYTEA NOT NULL,                  -- pgp_sym_encrypt
    app_key_encrypted   BYTEA,                           -- DD only
    site                TEXT NOT NULL DEFAULT 'datadoghq.com',
    validated_at        TIMESTAMPTZ,                     -- last successful test
    last_rotated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    key_fingerprint     TEXT NOT NULL,                   -- sha256(key)[:16] for audit/diff
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (tenant_id, provider)
);
-- RLS standard: USING (tenant_id = current_setting('app.current_tenant')::uuid)
```

The encryption master key lives in env var `PULSE_OBS_MASTER_KEY` (rotated
manually pre-R4). Compromise of the env var compromises ALL tenants — same
risk profile as `INTERNAL_API_TOKEN` today, accepted while we're a single
deployment unit. R4 migration to KMS-backed master key is filed in
`FDD-OBS-001-RISK-1` (CISO follow-up).

### Validation flow

```
1. POST /v1/admin/integrations/datadog/validate
     body: { api_key, app_key, site }
     auth: tenant_admin role
2. backend calls GET https://{site}/api/v1/validate (in-memory only)
3. on 200:
     - encrypt with PULSE_OBS_MASTER_KEY
     - UPSERT (tenant_id, provider) row
     - emit `integration.connected` Kafka event
4. on 401/403/timeout:
     - DO NOT persist
     - return error with hint ("verify your DD site domain")
```

### Rotation flow

```
1. Admin pastes new key → same /validate endpoint
2. on success:
     - UPDATE row + bump last_rotated_at + new key_fingerprint
     - publish `obs.credentials.rotated` Kafka event
     - connectors invalidate their in-memory cache (TTL is 5min anyway,
       so worst case 5min of stale 401s)
3. NO service restart. NO retry queue for in-flight requests; they fail
   gracefully (cached values + stale=true flag — see ADR-024).
```

### Logging discipline

- Raw key values are **never** logged. Logs reference `key_fingerprint`
  (`sha256(key)[:16]`) for auditability.
- The validation HTTP call uses a redacted client (no header dump).
- `pulse-ciso` review gate: pre-commit hook + integration test that
  greps for `api_key=` or full keys in log output.

## Consequences

### Positive
- Reuses the `tenant_jira_config` pattern operators already understand.
- No infra dependency for R2 (works in dev with `pgcrypto` extension).
- Sub-1ms credential fetch (Postgres lookup vs Secrets Manager 50ms).
- Migrating to Secrets Manager in R4 is a **pure data move** — schema
  becomes a thin shim that fetches from SM and caches.

### Negative
- Master key in env var = blast radius is the entire fleet if leaked.
  Mitigated by short-rotation discipline + R4 KMS migration plan.
- pgcrypto adds extension dependency to migration order; documented in
  schema-drift guard.
- Credential rotation requires coordinated cache invalidation (Kafka
  event + 5min TTL) — not instant.

### Migration to Secrets Manager (R4 trigger conditions)

We migrate when **any** of these triggers:

1. First regulated tenant onboards (HIPAA/PCI/SOC2 requirement).
2. Tenant count exceeds 500 (operational rotation cost > SM cost).
3. CISO escalation about master-key blast radius (separate FDD).

The migration itself is straightforward: schema becomes
`tenant_observability_credentials_secret_arn` (TEXT) replacing the
encrypted columns; provider abstraction layer (ADR-023) hides the change
from connectors.
