# Security Review — FDD-OBS-001: Observability Foundation (PRs #21 + #22)

**Review date:** 2026-05-04
**Reviewer:** pulse-ciso
**Branches:** `feat/obs-001-foundation` (PR #21), `feat/obs-001-skeleton` (PR #22)
**Risk rating:** High (pre-fix) → Medium (post-fix, with two deferred High items outstanding)

---

## Scope

Files reviewed:

ADRs:
- `pulse/docs/adrs/021-observability-credentials-per-tenant.md`
- `pulse/docs/adrs/025-observability-anti-surveillance-enforcement.md`
- `pulse/docs/adrs/026-observability-graceful-degradation.md`
- `pulse/docs/adrs/027-observability-bounded-context-placement.md`

Migrations:
- `pulse/packages/pulse-data/alembic/versions/016_tenant_feature_flags.py`
- `pulse/packages/pulse-data/alembic/versions/017_observability_credentials.py`
- `pulse/packages/pulse-data/alembic/versions/018_service_squad_ownership.py`
- `pulse/packages/pulse-data/alembic/versions/019_obs_metric_snapshots.py`

Code:
- `pulse/packages/pulse-data/src/shared/feature_flags.py`
- `pulse/packages/pulse-data/src/contexts/observability/models.py`
- `pulse/packages/pulse-data/src/contexts/observability/services/capability_detection.py`
- `pulse/packages/pulse-data/src/connectors/observability/base.py`
- `pulse/packages/pulse-data/src/connectors/observability/_anti_surveillance.py`
- `pulse/packages/pulse-data/tests/unit/test_obs_anti_surveillance.py`
- `pulse/packages/pulse-data/tests/conftest.py` (lines 525–572, `mock_observability_provider` fixture)

---

## Critical (block release)

None identified.

---

## High

### H-001: `PULSE_OBS_MASTER_KEY` has no minimum-length enforcement or rotation policy defined in code
**Files:** `pulse/docs/adrs/021-observability-credentials-per-tenant.md`, `pulse/packages/pulse-data/alembic/versions/017_observability_credentials.py`
**Status:** DEFERRED (must be addressed before PR 2 merges — PR 2 starts writing encrypted credential rows)

ADR-021 documents that `PULSE_OBS_MASTER_KEY` encrypts all tenant credentials via `pgp_sym_encrypt`. The threat model is acknowledged ("blast radius is the entire fleet if leaked"), but two concrete controls are absent from the code today:

**Gap 1 — No minimum key length enforced.**
`pgp_sym_encrypt` with a short passphrase is vulnerable to offline dictionary attacks if the database or a backup is exfiltrated. A 10-character passphrase produces qualitatively weaker ciphertext than a 32+ character random key, and the current schema, migration, and config layer impose no constraint. `pgp_sym_encrypt` uses OpenPGP's S2K (string-to-key) KDF internally; this helps but does not substitute for high entropy in the input.

**Gap 2 — No rotation cadence documented or enforced.**
ADR-021 mentions "rotated manually pre-R4" but does not define: how frequently, triggered by what events, what the migration procedure is when the key changes (re-encrypt all rows or store old key alongside), or who is responsible. R4 KMS migration is ~2 releases away. In the R2–R3 window with real tenant credentials encrypted under a static key, a leaked key has permanent retrospective impact on all stored data with no detection mechanism.

**Risk:** A developer deploys with a weak `PULSE_OBS_MASTER_KEY` (e.g., "dev123" left over from local testing). PR 2 immediately starts encrypting real Datadog API keys. The only protection against this is social/operational, not technical.

**Proposed fixes (must be in place before PR 2 merges):**

*1. Add a startup validation in `src/config.py`:*
```python
@model_validator(mode='after')
def validate_obs_master_key(self) -> 'Settings':
    key = self.pulse_obs_master_key
    if key is not None and len(key) < 32:
        raise ValueError(
            'PULSE_OBS_MASTER_KEY must be at least 32 characters. '
            'Generate with: openssl rand -base64 32'
        )
    return self
```

*2. Add a key fingerprint column to `tenant_observability_credentials` (already exists as `key_fingerprint`) — but ensure this records the key identity (e.g. sha256(master_key)[:8]) not just the credential fingerprint. This enables detection of "which rows were encrypted with which master key version" for rotation tracking.*

*3. Document the rotation runbook in `pulse/docs/security-reviews/obs-master-key-rotation-runbook.md` covering: (a) generate new key, (b) set `PULSE_OBS_MASTER_KEY_NEW` env var, (c) run re-encryption script (decrypt with old, re-encrypt with new, single transaction), (d) swap env var, (e) verify with a test tenant credential. This runbook must exist before R2 GA, not R4.*

**The absence of these controls is not a blocker for PR #21 alone (no credentials schema yet), but must be resolved before PR #22 can proceed to a production deployment or before the Datadog connector in PR 2 ships to any real tenant.**

---

### H-002: DB-level PII trigger uses `?` operator — checks top-level JSONB keys only, nested PII can bypass Layer 2
**File:** `pulse/packages/pulse-data/alembic/versions/018_service_squad_ownership.py`, lines 86–99
**Status:** DEFERRED (architectural — must be tracked with an explicit FDD)

The `obs_no_pii_in_metadata()` PL/pgSQL trigger uses PostgreSQL's `?` operator:
```sql
IF NEW.metadata ? k THEN
    RAISE EXCEPTION '...';
END IF;
```

The `?` operator checks for a key at the **top level of a JSONB object only**. It does not recurse. A vendor adapter that inadvertently returns (or that an attacker crafts) nested PII survives the trigger:

```sql
-- This PASSES the trigger silently:
INSERT INTO service_squad_ownership (..., metadata) VALUES
  (..., '{"attributes": {"user.email": "attacker@example.com"}}');

-- This PASSES the trigger silently (array wrapper):
INSERT INTO service_squad_ownership (..., metadata) VALUES
  (..., '{"events": [{"user": "alice@example.com"}]}');
```

**Why this matters:** The trigger is the last line of defense if Layer 1 (`strip_pii`) has a bug. If a vendor response contains deeply nested PII (Datadog traces, for instance, commonly nest `usr.email` 3–4 levels deep in span attributes), and a future adapter bug skips the `strip_pii` call, the trigger provides no protection and the PII reaches storage.

**Current partially-compensating controls:** Layer 1 (`strip_pii`) recursively strips nested keys correctly — the trigger gap only matters when Layer 1 fails. Layer 4 (CI lint) catches code-level references but not runtime adapter bugs. These compensating controls reduce likelihood but do not eliminate the risk at the DB layer.

**Proposed fix options:**

*Option A (preferred for simplicity) — Replace scalar `?` check with `jsonb_path_exists` for deep key detection:*
```sql
-- Instead of: IF NEW.metadata ? k THEN
-- Use:
IF jsonb_path_exists(NEW.metadata, ('$..**.' || k)::jsonpath) THEN
    RAISE EXCEPTION 'PII key % blocked in obs metadata (ADR-025 Layer 2)', k;
END IF;
```
Note: `jsonb_path_exists` is available from PostgreSQL 12+. The `$..**.<key>` path expression performs recursive descent. Verify the exact path syntax against the Postgres version in use (recommend a unit test in migration CI).

*Option B — Accept the limitation, but add an explicit comment in the migration and ADR-025 that Layer 2 is top-level only*, and compensate by hardening Layer 1 with an integration test that sends deeply nested PII through a mock adapter and asserts it is stripped before the DB call.

**For PR #22, Option B is the merge-unblocking path (document the gap explicitly rather than leave it undocumented). Option A should be a filed backlog item resolved before R2 GA.**

---

## Medium

### M-001: `strip_pii` does not handle dict keys with encoding tricks or Unicode look-alikes
**File:** `pulse/packages/pulse-data/src/connectors/observability/_anti_surveillance.py`
**Status:** DEFERRED (low near-term risk — document + test)

`_is_forbidden` does `key.lower() in FORBIDDEN_FIELD_NAMES`. This catches basic case variations but does not handle:

1. **Unicode normalization tricks**: `ｕｓｅｒ` (fullwidth U+FF55 etc.) does not lower-case to `user`. A vendor that inadvertently uses fullwidth or Unicode-escaped keys in its JSON response (uncommon, but documented in real Datadog trace attributes with custom tags from non-ASCII environments) would bypass the check.

2. **Dotted-key aliasing**: Some vendors return `{"user": {"email": "..."}}` as a legitimate nested structure, and others flatten it to `{"user.email": "..."}`. The forbidden set contains both `user` and `user.email`. `strip_pii` correctly strips `user` as a top-level key (removing the entire subtree). However, if a vendor returns `{"usr": {"email": "..."}}` — the Datadog convention for APM spans (`usr.email` is in the forbidden set only as the dotted form, not as nested `{"usr": {"email": ...}}`), then the nested variant survives Layer 1.

**Risk:** Low today (no real adapters ship in PR #22). High when the Datadog adapter lands in PR 2 and processes real APM span data.

**Proposed fix:** Extend `FORBIDDEN_FIELD_NAMES` to include the parent key for every dotted-pair forbidden name:
```python
# If "usr.email" is forbidden, also forbid the parent key "usr" when
# its value is a dict containing "email". Add helper:
FORBIDDEN_PARENT_CHILD_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ("usr", "email"),
    ("user", "email"),
    ("user", "id"),
    ("trace", "user_id"),
    ("rum", "user_id"),
})

def strip_pii(record: Any) -> Any:
    if isinstance(record, dict):
        cleaned = {}
        for k, v in record.items():
            if not isinstance(k, str):
                cleaned[k] = strip_pii(v)
                continue
            if _is_forbidden(k):
                # ... existing strip
                continue
            # Strip parent when child pair is forbidden
            if isinstance(v, dict) and any(
                (k.lower(), ck) in FORBIDDEN_PARENT_CHILD_PAIRS
                for ck in v.keys()
            ):
                logger.debug("anti-surveillance: stripped parent key %r with PII child", k)
                continue
            cleaned[k] = strip_pii(v)
        return cleaned
    ...
```
File this with a test case using `{"usr": {"email": "x@y.com"}}` before the Datadog adapter ships.

---

### M-002: `tenant_feature_flags.metadata` JSONB has no PII guard trigger
**File:** `pulse/packages/pulse-data/alembic/versions/016_tenant_feature_flags.py`
**Status:** DEFERRED (flag for PR #22 follow-up)

`tenant_observability_credentials` and `service_squad_ownership` and `obs_metric_snapshots` all have the `obs_no_pii_in_metadata()` trigger. `tenant_feature_flags` also has a `metadata JSONB` column but no equivalent trigger. The current use case for this metadata column is operator-controlled flag context (e.g. rollout percentage, comments) — low PII risk for now. However, the pattern of "every metadata JSONB column gets a PII guard trigger" should be established as a convention.

If a future feature stores observability context in flag metadata (e.g. "this flag was enabled because tenant connected Datadog on date X, provider_id Y"), the metadata column becomes a vector for PII-adjacent data without the protection that exists on the obs tables.

**Proposed fix:** Apply the same trigger to `tenant_feature_flags` in a follow-up migration (can be bundled with other migration work). Or at minimum, add a code comment in the migration explicitly noting that feature-flag metadata is operator-facing only and must never carry provider/user data.

---

### M-003: `capability_detection.py` queries have no timeout — hung DB query masks capability state
**File:** `pulse/packages/pulse-data/src/contexts/observability/services/capability_detection.py`
**Status:** DEFERRED (must be resolved before rollup worker ships in PR 4)

`get_capabilities()` executes three sequential queries (credentials, ownership, snapshots). Each uses `await session.execute(text(...))` with no query timeout. If the DB is slow (e.g. `obs_metric_snapshots` grows to millions of rows and the index stats are stale) or locked (bulk insert in progress), the capability detection call hangs indefinitely.

The outer `except Exception` catch returns `ObservabilityCapabilities.empty()` on any error — but this only fires if the exception is raised. A hung query waiting on a lock does not raise until the lock is released (which could be minutes). During this window, every route that calls `get_capabilities()` before rendering blocks.

The ADR-026 contract says "Never return 5xx for 'tenant doesn't have provider'" but does not address "route hangs for 90s waiting for capability detection".

**Risk:** Medium — DB load issues could cause all Signals routes to hang simultaneously, degrading the entire dashboard for affected tenants.

**Proposed fix:** Wrap each query with a statement timeout. Either at the SQLAlchemy level via execution options or via PostgreSQL SET LOCAL:
```python
await session.execute(text("SET LOCAL statement_timeout = '2000'"))  # 2s
creds_row = await session.execute(text("SELECT ..."), ...)
```
Alternatively, use SQLAlchemy's `execution_options(timeout=2)` if the driver supports it. The outer `except Exception` will then correctly catch `asyncio.TimeoutError` or the `QueryCanceledError` from Postgres and return `empty()` within a bounded latency.

---

### M-004: Feature flag `set_flag()` has no RBAC enforcement at the shared-module level
**File:** `pulse/packages/pulse-data/src/shared/feature_flags.py`
**Status:** DEFERRED (R1 RBAC — document)

`set_flag(tenant_id, flag_key, enabled)` is a public write function in a shared module. It relies entirely on the caller to have verified that the calling principal is an authorized tenant administrator. There is no guard at the function level. Any code path that can obtain a valid `tenant_id` UUID can enable any feature flag for that tenant without restriction.

For MVP (single deployment, trusted internal callers), this is acceptable. When the API layer exposes a `POST /admin/flags/:flag_key` endpoint (inevitable once OBS is in use), a missing route-level guard would allow any authenticated tenant member (not just admins) to toggle flags.

**Action required at R1:** The route handler that calls `set_flag()` must enforce `tenant_admin` role via an RBAC guard before the call. A comment in `feature_flags.py` should state: "Callers are responsible for verifying the principal has tenant_admin role before invoking set_flag."

---

### M-005: `key_fingerprint` column stores only 16 hex chars of sha256 — collision risk in rotation audit
**File:** `pulse/packages/pulse-data/alembic/versions/017_observability_credentials.py`, line 51; `pulse/docs/adrs/021-observability-credentials-per-tenant.md`, line 53
**Status:** DEFERRED (low operational impact — flag)

ADR-021 defines `key_fingerprint` as `sha256(key)[:16]` — the first 16 hex characters of the SHA-256 hash, representing only 8 bytes / 64 bits of the hash output. For the purpose stated (audit/diff, distinguishing key rotations), 64 bits provides 2^32 expected collisions, which is practically sufficient for a per-tenant rotation audit trail (no tenant will rotate credentials 4 billion times). However, the ORM model defines `key_fingerprint` as `String(32)`, leaving 16 bytes available. The discrepancy between the 16-char ADR spec and the 32-char column is a documentation mismatch rather than a security flaw.

Separately, if the fingerprint is ever used for any security-critical comparison (e.g. "has this credential been seen before" to detect replay), 64-bit truncated hashes are insufficient. Confirm in ADR-021 or code comments that `key_fingerprint` is purely informational and never used for security decisions.

**Proposed fix:** Increase the truncation to 32 hex chars (16 bytes / 128 bits) to match the column width and provide comfortable uniqueness headroom. Update the ADR-021 spec line accordingly. This is a one-line change in `CredentialService` (PR 2).

---

### M-006: `obs_metric_snapshots` has no retention policy — unbounded table growth
**File:** `pulse/packages/pulse-data/alembic/versions/019_obs_metric_snapshots.py`
**Status:** DEFERRED (operational — pre-R2 GA)

`obs_metric_snapshots` stores hourly rollup buckets per (tenant, provider, service, metric). For a tenant with 100 services × 6 metrics × 8760 hours/year = 5.256M rows per tenant per year. At 500 tenants (the R4 threshold), this is 2.6B rows with no archival or deletion strategy. The `ix_oms_timeline` index is correct for query performance but says nothing about data lifetime.

No TTL trigger, partition strategy, or cleanup job is defined in this migration or in any referenced worker (rollup worker ships in PR 4). This is not a security vulnerability per se, but:

1. An excessively large table increases the blast radius of a `tenant_id` RLS bypass (more data exposed per compromise).
2. Unbound historical data creates a GDPR/LGPD "right to deletion" compliance gap — there is no mechanism to delete a departed tenant's observability history.

**Proposed fix:** File a backlog item to (a) add a `PARTITION BY RANGE (hour_bucket)` strategy or a time-based cleanup stored procedure before R2 GA, and (b) ensure the tenant deletion flow (already needed for GDPR) covers `obs_metric_snapshots`.

---

## Low

### L-001: `_strip_strings_and_comments` in the CI lint test is regex-based and can be fooled by edge-case string escaping
**File:** `pulse/packages/pulse-data/tests/unit/test_obs_anti_surveillance.py`, lines 57–73
**Status:** Informational — accept for MVP, note for R2

The `_strip_strings_and_comments` function uses regex to remove strings before scanning for forbidden identifiers. Python's string escaping, especially raw strings (`r"user.email"`) and byte strings (`b"user.email"`), may not be stripped by the current patterns:

```python
# Current regex removes: "user.email" and 'user.email'
# Does NOT handle: r"user.email", b"user.email", rb"user.email"
```

A developer writing `raw_field = r"user.email"` in an adapter would not be caught by Layer 4, even though the string literal contains a forbidden ref that would be active at runtime.

Additionally, multi-line strings that use implicit concatenation:
```python
field = ("user"
         ".email")
```
would not be caught by the string regex (neither fragment matches a forbidden ref individually).

**Risk:** Low — these are unlikely patterns in the codebase and the multi-layer defense means a missed lint scan does not alone enable a PII leak. Layer 1 (`strip_pii`) and Layer 2 (DB trigger) remain independent.

**Proposed fix:** Add `rb"`, `r"`, `b"` prefixed string patterns to the regex list in `_strip_strings_and_comments`. Flag the implicit concatenation gap as a known limitation in a comment in the test.

---

### L-002: `tenant_observability_credentials` RLS INSERT policy is `WITH CHECK` only — no `USING` clause for SELECT path
**File:** `pulse/packages/pulse-data/alembic/versions/017_observability_credentials.py`, lines 63–78
**Status:** Confirmed correct — informational only

The migration applies RLS policies with the following clauses:
- SELECT → USING
- INSERT → WITH CHECK
- UPDATE → USING
- DELETE → USING

This is the correct PostgreSQL RLS pattern. `WITH CHECK` on INSERT is correct (it checks the row being inserted, not an existing row). `USING` on SELECT/UPDATE/DELETE is correct (it filters existing rows). This is consistent with migration 016 and the existing multi-tenant pattern. Confirmed — no action required.

---

### L-003: `site` column in `tenant_observability_credentials` has no validation against known Datadog site domains
**File:** `pulse/packages/pulse-data/alembic/versions/017_observability_credentials.py`, line 48
**Status:** DEFERRED (PR 2 scope — flag)

The `site` column stores region-specific Datadog endpoint domains (e.g. `datadoghq.com`, `datadoghq.eu`, `us3.datadoghq.com`). It has a default but no CHECK constraint restricting it to known valid values. A tenant admin (or a compromised admin session) could store an arbitrary domain in this column. When the Datadog adapter (PR 2) constructs its HTTP client URL from this column, it would issue API calls to an attacker-controlled domain, effectively becoming an SSRF (Server-Side Request Forgery) vector or at minimum leaking the tenant's credentials to a third-party endpoint.

**Proposed fix (must be in PR 2, not optional):** Add a CHECK constraint to the `site` column restricting to the known Datadog site registry:
```sql
CONSTRAINT ck_obs_creds_site CHECK (
    site IN (
        'datadoghq.com',
        'datadoghq.eu',
        'us3.datadoghq.com',
        'us5.datadoghq.com',
        'ap1.datadoghq.com',
        'ddog-gov.com'
    )
)
```
This prevents SSRF via credential upsert. Apply equivalent validation in the API layer (DTO validation in NestJS, Pydantic validator in FastAPI) for defense in depth. The `CredentialService` in PR 2 must validate `site` before constructing any HTTP URL.

---

### L-004: `mock_observability_provider` fixture uses `MagicMock` — sync attribute on async Protocol risks false-positive tests
**File:** `pulse/packages/pulse-data/tests/conftest.py`, lines 555–570
**Status:** Informational — flag for test-engineer

The `_build` factory returns `MagicMock()` for the provider object, with async methods replaced by `AsyncMock`. The `provider_id` attribute is a plain string assignment on a `MagicMock`. This works structurally for tests but has one risk: since `MagicMock` auto-creates any attribute accessed on it, a test that accesses `provider.nonexistent_method()` will not raise `AttributeError` — it will return a new `MagicMock`, silently making the assertion pass even if the code under test is accessing a wrong method name. With structural typing (Protocol), this means a test could pass against the mock even if the adapter does not implement the Protocol correctly.

**Proposed fix:** Replace `MagicMock()` with `create_autospec` against the `ObservabilityProvider` Protocol or use a `spec=` parameter:
```python
from unittest.mock import AsyncMock, create_autospec
from src.connectors.observability.base import ObservabilityProvider

provider = create_autospec(ObservabilityProvider, instance=True)
provider.provider_id = provider_id
provider.list_deployments = AsyncMock(return_value=deployments or [])
# etc.
```
This ensures any test that calls a method not on the Protocol contract will fail immediately. Low priority but important for test fidelity before the real Datadog adapter ships.

---

### L-005: No audit log on feature flag changes (write path)
**File:** `pulse/packages/pulse-data/src/shared/feature_flags.py`, lines 187–221
**Status:** DEFERRED (R1)

`set_flag()` writes to `tenant_feature_flags` and invalidates the Redis cache but emits no audit event. For feature flags that gate paid features (e.g. `obs.signals.enabled` enabling R2 Signals for a tenant), there is no record of who set the flag, when, or what it was set to before the change. `updated_at` exists but records only the timestamp, not the actor.

**For R1 compliance (SOC 2 control evidence):** Add a Kafka event or a separate `feature_flag_audit` table entry on every `set_flag()` call recording `(tenant_id, flag_key, old_value, new_value, actor_id, changed_at)`.

---

## Informational

### I-001: RLS on all 4 new tables — confirmed correct pattern
**Files:** Migrations 016–019

All four tables have RLS enabled (`ALTER TABLE ... ENABLE ROW LEVEL SECURITY`) with four policies each (SELECT/INSERT/UPDATE/DELETE). All policies use `current_setting('app.current_tenant')::uuid` as the RLS predicate. Pattern is consistent with the established codebase standard. Confirmed.

---

### I-002: Composite PKs without `TenantModel` — RLS still enforced correctly
**Files:** `pulse/packages/pulse-data/src/contexts/observability/models.py`

The `models.py` docblock correctly documents the decision to inherit from `Base` directly. The concern is whether `tenant_id` is enforced as NOT NULL without `TenantModel`. Confirmed: all three composite PKs include `tenant_id` as a primary key component, making it implicitly NOT NULL at the Postgres level. RLS policies reference `tenant_id` directly. The absence of a synthetic UUID `id` column does not affect RLS correctness — the RLS policy evaluates against the row's `tenant_id` value regardless of primary key structure. Architecture is sound.

---

### I-003: `strip_pii` is non-mutating and handles tuples — confirmed
**File:** `pulse/packages/pulse-data/src/connectors/observability/_anti_surveillance.py`

`strip_pii` constructs `cleaned` as a new dict on each call, does not modify the input `record`, and recurses into `list`, `tuple`, and nested `dict` values. The non-mutating design is correct: adapters that pass vendor response dicts to `strip_pii` retain the original for debugging purposes if needed. The handling of `tuple` (line 70) is a defensive addition — JSON has no tuples, but Python adapter code may use tuples for intermediate representations. Confirmed correct.

---

### I-004: `ObservabilityCapabilities.empty()` classmethod — correct fail-closed behavior
**File:** `pulse/packages/pulse-data/src/connectors/observability/base.py`, lines 119–132

`ObservabilityCapabilities.empty()` returns all boolean flags as `False` and numeric/date fields as `None` or `0.0`. This is the correct fail-closed posture per ADR-026 Principle 4 — capability detection failures cause the system to render honest empty states, not to assume capabilities exist. The `rate_limit_remaining=None` (not 0) is semantically correct: `None` means "not yet measured" whereas `0` would mean "bucket exhausted". Confirmed.

---

### I-005: Forbidden key lists are synchronized across Layers 1, 2, 4 — confirmed with one gap
**Files:** `_anti_surveillance.py`, migration `018`, `test_obs_anti_surveillance.py`

The forbidden key set across the three locations is:

| Key | Layer 1 (`FORBIDDEN_FIELD_NAMES`) | Layer 2 (migration 018 trigger) | Layer 4 (FORBIDDEN_REFS) |
|---|---|---|---|
| `user` | yes | yes | no |
| `user_id` | yes | yes | no |
| `user.id` | yes | yes | `user.id` yes |
| `user.email` | yes | yes | yes |
| `deployment.author` | yes | yes | yes |
| `alert.assignee` | yes | yes | yes |
| `incident.assignee` | yes | yes | yes |
| `owner.email` | yes | yes | yes |
| `ack_by` | yes | yes | yes |
| `resolved_by` | yes | yes | yes |
| `creator` | yes | yes | no |
| `modified_by` | yes | yes | no |
| `trace.user_id` | yes | yes | yes |
| `rum.user_id` | yes | yes | yes |
| `usr.email` | yes | yes | yes |

The Layer 4 lint scan (`FORBIDDEN_REFS` in `test_obs_anti_surveillance.py`) does **not** include `user`, `user_id`, `creator`, or `modified_by`. This means business code that accesses a field literally named `creator` in code would not be flagged by the CI lint. These are lower-risk omissions (`creator` and `modified_by` are less likely to appear as variable names in adapter code than `user.email`) but the gap should be documented. The cross-layer verification test (`test_forbidden_ref_present_in_strip_pii_set`) only validates Layer 4 → Layer 1 direction; it does not validate that all Layer 1 entries are in Layer 4. Add an inverse assertion.

---

### I-006: `capability_detection.py` query is read-only and parameterized — confirmed SQL-injection safe
**File:** `pulse/packages/pulse-data/src/contexts/observability/services/capability_detection.py`

All three SQL queries use `text(...)` with named bind parameters (`:tenant_id`, `:since_30d`). No string interpolation in SQL. SQLAlchemy handles parameter escaping at the driver level. The service performs no writes. Confirmed SQL-injection safe.

---

### I-007: `feature_flags.py` uses parameterized queries and validates `flag_key` is non-empty
**File:** `pulse/packages/pulse-data/src/shared/feature_flags.py`

Both `_read_db` and `set_flag` use `text(...)` with bind parameters. `set_flag` raises `ValueError` when `flag_key` is empty. `is_enabled` returns `False` on empty `flag_key` without touching the DB. The Redis cache key `f"ff:{tenant_id}:{flag_key}"` uses plain string formatting — this is safe because Redis key namespacing is not a security boundary and the values are `tenant_id` (UUID format) + `flag_key` (operator-controlled string, never user-supplied in production). Confirmed correct.

---

### I-008: ADR-026 graceful degradation contract is partially implemented in PR #22 — confirmed correct scope
**File:** `pulse/packages/pulse-data/src/contexts/observability/services/capability_detection.py`

PR #22 ships the always-empty path: `get_capabilities()` queries live tables and returns `ObservabilityCapabilities.empty()` when no provider is connected. The implementation explicitly notes that `has_deploy_markers` is approximated from `has_metric_signal` until PR 2 (this is a documented TODO, not a bug). The outer `except Exception` catch with graceful `empty()` return correctly implements ADR-026 Principle 4. The short-circuit at `not has_provider` (line 63) is correct — no ownership or metric data can exist without a provider row. Confirmed.

---

### I-009: `ObservabilityProvider` Protocol exposes `vendor_raw` field — correctly fenced against business-code use
**File:** `pulse/packages/pulse-data/src/connectors/observability/base.py`

`DeployMarker.vendor_raw` and `ServiceEntity.vendor_raw` are documented as "business code MUST NOT read from it" with the note that CI lint enforces this (ADR-025 L4). The CI lint test in `test_obs_anti_surveillance.py` scans for `FORBIDDEN_REFS` but does NOT scan for accesses to `.vendor_raw` in business code (it is a valid field name in the Protocol, not a forbidden string). The protection is convention-only for this field. This is an accepted design choice (the field is needed for adapter debugging) but worth noting that if a future developer reads `vendor_raw` in `contexts/observability/services/`, the lint will not catch it. Consider adding `"vendor_raw"` to the scan scope with a comment explaining context (only allowed in `connectors/`, forbidden in `contexts/`).

---

### I-010: GDPR / LGPD compliance — stored observability metadata residual risk
**Scope:** ADR-021, migrations 017–019

Even with PII stripped, observability data in `obs_metric_snapshots` and `service_squad_ownership` constitutes potentially personal data under LGPD Article 5 when it can be combined with other tenant data to re-identify individuals indirectly. For example, `service_name = "checkout-service"` combined with squad ownership records and deployment timing could correlate to specific engineers during on-call periods. This is a known risk under PULSE's anti-surveillance posture (ADR-011) and is accepted by design — the schema deliberately lacks user dimensions. However, the right-to-deletion flow must cover these tables. Confirm that the tenant deletion procedure (an existing gap in PULSE's compliance roadmap) includes `DELETE FROM obs_metric_snapshots WHERE tenant_id = :id` and `DELETE FROM service_squad_ownership WHERE tenant_id = :id`. File this as a GDPR/LGPD compliance check in the R4 SOC 2 roadmap.

---

## Summary of Findings by Severity

| ID | Severity | Title | Status |
|----|----------|-------|--------|
| H-001 | High | Master key has no minimum length enforcement or rotation runbook | DEFERRED (must fix before PR 2 merges) |
| H-002 | High | PII trigger checks top-level JSONB only — nested PII bypasses Layer 2 | DEFERRED (document gap; Option B for PR #22 merge; Option A for R2 GA) |
| M-001 | Medium | `strip_pii` does not handle Unicode look-alikes or dotted-key nesting | DEFERRED (pre-Datadog adapter) |
| M-002 | Medium | `tenant_feature_flags.metadata` lacks PII trigger | DEFERRED (follow-up migration) |
| M-003 | Medium | `capability_detection` queries have no timeout — hang risk | DEFERRED (before rollup worker PR 4) |
| M-004 | Medium | `set_flag()` has no RBAC guard at function level | DEFERRED (R1 RBAC) |
| M-005 | Medium | `key_fingerprint` is 16 hex chars — column says 32 | DEFERRED (PR 2 one-liner) |
| M-006 | Medium | `obs_metric_snapshots` has no retention policy | DEFERRED (pre-R2 GA) |
| L-001 | Low | CI lint regex misses `r"..."` / `b"..."` prefix strings | Accept for MVP — document |
| L-002 | Low | RLS pattern on credentials table — confirmed correct | Informational |
| L-003 | Low | `site` column has no CHECK constraint — SSRF vector in PR 2 | DEFERRED (must fix in PR 2) |
| L-004 | Low | `mock_observability_provider` uses `MagicMock` not `create_autospec` | DEFERRED (test quality) |
| L-005 | Low | No audit log on feature flag changes | DEFERRED (R1) |
| I-001–I-010 | Info | Various confirmations and notes | Confirmed |

---

## Fixes Applied

None in this review. PR #21 and PR #22 are pure greenfield additions with no pre-existing code to fix at time of review. All findings are either deferred with explicit action items or confirmed correct.

---

## Fixes Deferred

| Fix | File | Required by | Reason |
|-----|------|-------------|--------|
| H-001 | `src/config.py` + ADR-021 rotation runbook | Before PR 2 merges | Minimum key length enforcement is a one-line validator; rotation runbook is an ops doc. No technical blocker, only prioritization. |
| H-002 | Migration 018 trigger + ADR-025 | PR #22 merge — document; R2 GA — recursive fix | PostgreSQL `?` operator limitation. Option A (jsonb_path_exists) requires migration 020. Option B (document + harden Layer 1 integration test) acceptable for merge. |
| M-001 | `_anti_surveillance.py` | Before Datadog adapter (PR 2) | Extend FORBIDDEN_PARENT_CHILD_PAIRS, add test case with nested `{"usr": {"email": ...}}`. |
| M-002 | Migration 016 follow-up | Next available migration slot | Add `obs_no_pii_in_metadata` trigger to `tenant_feature_flags`. Low priority given metadata's current use. |
| M-003 | `capability_detection.py` | Before PR 4 (rollup worker) | Add `SET LOCAL statement_timeout = '2000'` to each DB call. |
| M-004 | Route handler that calls `set_flag` | R1 RBAC implementation | Add comment to `set_flag` docstring. Route guard required when endpoint is exposed. |
| M-005 | `CredentialService` (PR 2) | PR 2 | Change `sha256(key)[:16]` to `sha256(key)[:32]` (16 bytes hex). |
| M-006 | Migration or rollup worker (PR 4) | Pre-R2 GA | Define retention policy / partition scheme for `obs_metric_snapshots`. |
| L-003 | Migration 017 + API DTO (PR 2) | PR 2 — must not ship Datadog adapter without this | Add CHECK constraint on `site` column. Validate in FastAPI/NestJS before HTTP URL construction. |
| L-004 | `tests/conftest.py` | Before Datadog adapter test suite (PR 2) | Replace `MagicMock` with `create_autospec(ObservabilityProvider, instance=True)`. |
| L-005 | `feature_flags.py` or new `feature_flag_audit` table | R1 | Emit Kafka event or audit row on every `set_flag()` call. |

---

## Risk Rating

**Current (PRs #21 + #22 as-is, before PR 2): High**
**Post-H-001 and H-002-B documentation applied: Medium**

Justification:

PRs #21 and #22 ship schema, models, protocol definitions, and anti-surveillance infrastructure. They do not ship any code that encrypts, decrypts, or transmits real credentials — that lands in PR 2. The High rating reflects two pre-existing gaps that become actively exploitable the moment PR 2 ships:

1. A developer can deploy with a weak `PULSE_OBS_MASTER_KEY` and the system will silently accept it, encrypting real Datadog keys under a low-entropy passphrase (H-001).
2. Nested PII in vendor responses that survives `strip_pii` due to a future adapter bug will also survive the DB trigger, because the trigger only checks top-level JSONB keys (H-002).

**These PRs are safe to merge to main as-is because they contain no encryption or live API calls.** However, they must not advance to a production deployment or unblock PR 2 until H-001's minimum-key-length enforcement is in `src/config.py` and H-002's gap is explicitly documented in ADR-025 (with a follow-up migration filed in backlog). The L-003 SSRF gap (`site` column) is a hard blocker for the Datadog connector in PR 2 but not for this foundation.

**PRs #21 + #22 are approved for merge to main with the condition that the H-001 config validator and H-002 ADR documentation note are committed before or alongside the merge. The three items listed as "must fix in PR 2" (H-001 enforcement, H-002-Option-A or documented intent, L-003 SSRF constraint) are pre-conditions for PR 2 approval.**
