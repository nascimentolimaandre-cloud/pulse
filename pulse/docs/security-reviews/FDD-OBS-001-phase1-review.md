# FDD-OBS-001 Phase 1 — CISO Security Review

**Branch:** `feat/obs-001-phase1-backend-fixes`
**Commits reviewed:** 473c561, 65bee6d, 810af43, 64bb479, 1cbdd1a, 802a3e7
**Files changed:** 16 (+2040 LoC)
**Test baseline:** 293 unit + 19 integration (+66 from baseline)
**Review date:** 2026-05-11
**Reviewer:** PULSE (CISO agent)
**Verdict:** CONDITIONAL APPROVE — 3 must-fix items (FIND-001, FIND-003, FIND-004) before merge

---

## Severity Classification

| ID | Severity | Area | Title | Decision |
|----|----------|------|-------|----------|
| FIND-001 | HIGH | T1.4 + routes.py | `logger.exception` in `validate_datadog_credential` bypasses SanitizingExceptionMiddleware | Must fix this PR |
| FIND-002 | HIGH | T1.2 | Plaintext API key crosses the wire (Python process memory) during rotation — two-step decrypt+update | Must document risk; accept with runbook note |
| FIND-003 | MEDIUM | T1.4 | `SanitizingExceptionMiddleware` does not pass through `HTTPException` — swallows legitimate 4xx | Must fix this PR |
| FIND-004 | MEDIUM | T1.5 | Recursive PII trigger keys drift silently from `FORBIDDEN_FIELD_NAMES` — no contract test guards the SQL side | Must fix this PR |
| FIND-005 | MEDIUM | T1.6 | `FORBIDDEN_SQL_COLUMNS` incomplete — missing `merged_by`, `requested_reviewers`, `pr.committer` | Fix in Phase 2 |
| FIND-006 | MEDIUM | routes.py | `detail=str(exc)` and `detail=f"Provider call failed: {exc}"` leak exception text to HTTP clients | Fix in Phase 2 |
| FIND-007 | LOW | T1.4 | `__notes__` (PEP 678) not cleared before logging class name — theoretical Python 3.11+ risk | Accept (Python 3.9 in use) |
| FIND-008 | LOW | T1.2 | `PULSE_OBS_ROTATION_DATABASE_URL` override env var enables pointing rotation at an arbitrary host | Accept with runbook |
| FIND-009 | LOW | T1.5 | Recursive CTE has no depth guard — adversarial deeply-cyclic JSONB could trigger excessive recursion in PostgreSQL | Accept (postgres internal limit applies; metadata column is operator-controlled) |
| FIND-010 | INFORMATIONAL | T1.1 | `MonitorState.vendor_raw` — PII obligation is documented in docstring but not enforced by the Protocol contract | Track in Phase 2 |
| FIND-011 | INFORMATIONAL | T1.3 | `flow_health_on_demand.py:450` and `pipeline/routes.py:969` f-string SQL exceptions are audited and correct; no action needed | Closed |
| FIND-012 | INFORMATIONAL | T1.1 | Protocol typing is sound; `@runtime_checkable` + `isinstance` check at adapter construction time prevents silent duck-typing failures | Closed |

---

## Detailed Findings

---

### FIND-001 — HIGH — Must fix this PR

**CWE:** CWE-532 (Insertion of Sensitive Information into Log File)

**File:Line:** `src/contexts/observability/routes.py:124-128`

**Exploit scenario:**

The `validate_datadog_credential` endpoint catches a raw `Exception` from `provider.health_check()` and calls `logger.exception(...)`. `logger.exception` is a shorthand for `logger.error(..., exc_info=True)`, which attaches the full Python traceback — including local variable bindings — to the log record. At the call site, `exc` is in scope, and depending on the asyncpg/httpx driver path, the exception's `__context__` or `__cause__` may carry the HTTP response body or a prepared-statement string containing the API key (the exact leak pattern that T1.4 was designed to close).

This is a direct bypass: `SanitizingExceptionMiddleware` only catches exceptions that propagate out of the route handler uncaught. An exception caught INSIDE the route handler, logged via `logger.exception`, and then re-raised as an `HTTPException` NEVER reaches the middleware. The sanitization contract is broken at this call site.

Even if `health_check()` itself does not currently leak keys in its exception, the pattern is wrong and will be exploited the moment a driver-level error propagates into `health_check()` (which the module comment in `exception_middleware.py` explicitly warns about for asyncpg/httpx).

**Recommended fix:**

```python
except Exception:
    logger.error(
        "[obs-admin] datadog validate unexpected error tenant=%s site=%s "
        "err_class=%s request_id=%s",
        tenant_id, body.site,
        type(sys.exc_info()[1]).__name__,
        str(uuid.uuid4()),
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Could not reach Datadog. Check site/network and try again.",
    )
```

Do not use `from exc` on the re-raise to avoid leaking the original exception into the `HTTPException.__cause__` (which FastAPI may serialize in some error-handler paths). Suppress with `from None` or raise without chaining.

---

### FIND-002 — HIGH — Accept with runbook note

**CWE:** CWE-312 (Cleartext Storage of Sensitive Information — in-process memory)

**File:Line:** `scripts/rotate_obs_master_key.py:144-160, 181-212`

**Observation:**

The rotation strategy is described in the module docstring as: "decrypt with OLD inside postgres, immediately re-encrypted with NEW, in a single transaction." This is NOT what the code implements.

The code implements a TWO-STEP approach:
1. Step 1 (`async with engine.connect()`): `pgp_sym_decrypt` runs inside postgres, and the plaintext api_key is **returned to Python** via `drow.api_key`. It crosses the wire from postgres to the Python process as cleartext.
2. Step 2 (`async with engine.begin()`): A separate transaction runs `pgp_sym_encrypt` with the plaintext bound as `:plain_api`.

This means the plaintext API key exists in Python heap memory between the two transactions. The window is small (microseconds per row), but it is real. The module docstring's "plaintext decrypt happens INSIDE postgres" claim is misleading.

**Risk assessment:** This is the right approach given that the `key_fingerprint` must be recomputed in Python (SHA-256 is not native pgcrypto). A true single-transaction approach would require a postgres UDF. The risk is acceptable for the current threat model (disk swap, core dump, memory scraping of a container would be needed — not a remote attack).

**Required action:** Correct the module docstring from "Plaintext decrypt happens INSIDE postgres" to accurately reflect the two-step model. Add a note to the runbook's "What rotation does" section explicitly stating: "The plaintext API key transits Python heap memory between the decrypt and re-encrypt steps. The window is intentional (fingerprint must be computed in Python) and short, but the key is NOT confined exclusively to postgres during rotation."

**Decision:** Accept the implementation as-is; fix the documentation before merge.

---

### FIND-003 — MEDIUM — Must fix this PR

**CWE:** CWE-755 (Improper Handling of Exceptional Conditions)

**File:Line:** `src/shared/exception_middleware.py:62-81`

**Exploit scenario:**

`SanitizingExceptionMiddleware` catches `Exception` unconditionally, including `HTTPException`. This means:
- A `RequestValidationError` (422 Unprocessable Entity) raised by FastAPI's Pydantic validation will be caught and converted to an opaque 500.
- A deliberately raised `HTTPException(status_code=422, detail="site is invalid")` will also be swallowed.

The impact is twofold: (a) legitimate API clients lose 422 validation error detail that they need to correct their request; (b) the 422 that `InvalidSiteError` deliberately triggers via the `HTTPException` handler will become an opaque 500, confusing operators.

Starlette's `BaseHTTPMiddleware` is supposed to let `HTTPException` pass through to FastAPI's default exception handler (which renders the detail field), but wrapping `call_next` in a bare `except Exception` breaks this.

**Recommended fix:**

```python
from fastapi import HTTPException as FastAPIHTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException

async def dispatch(self, request, call_next):
    try:
        return await call_next(request)
    except (FastAPIHTTPException, StarletteHTTPException):
        raise   # Let FastAPI's default handler render the detail field
    except Exception as exc:
        # ... sanitized logging + opaque 500 as currently implemented
```

This preserves the 422/404/409 semantic contracts while still sanitizing unhandled driver-level exceptions.

**Test required:** Add a fifth test to `test_exception_middleware.py` that raises `HTTPException(status_code=422, detail="test detail")` from a route and asserts: (a) response status is 422, not 500; (b) response body contains the original detail string; (c) no sanitization log record is emitted.

---

### FIND-004 — MEDIUM — Must fix this PR

**CWE:** CWE-710 (Improper Adherence to Coding Standards — drift between duplicate security lists)

**File:Line:** `alembic/versions/023_obs_pii_trigger_recursive.py:51-56` vs `src/connectors/observability/_anti_surveillance.py:28-33`

**Observation:**

The migration comment says "Forbidden key list mirrors the Python `FORBIDDEN_FIELD_NAMES` from `_anti_surveillance.py` (kept in lockstep by a test in `test_obs_anti_surveillance.py`)." But no such contract test exists in `test_obs_anti_surveillance.py`. The tests there validate Python-layer behavior (strip_pii, forbidden_refs lint, sql columns). None of them parse `023_obs_pii_trigger_recursive.py` and compare the `_FORBIDDEN_KEYS` tuple against `FORBIDDEN_FIELD_NAMES`.

This means the two lists can drift silently on every future migration. The migration's downgrade path also hardcodes the key list (line 130-141) — another divergence point.

**Current state of sync:** Spot check shows the two lists match today, but the contract is unenforced at the code level.

**Required fix:** Add a contract test in `tests/unit/test_obs_anti_surveillance.py` (or `tests/contract/`) that:
1. Imports `FORBIDDEN_FIELD_NAMES` from `_anti_surveillance.py`.
2. Parses `alembic/versions/023_obs_pii_trigger_recursive.py` (or imports `_FORBIDDEN_KEYS` directly from the migration module if importable).
3. Asserts `set(_FORBIDDEN_KEYS) == FORBIDDEN_FIELD_NAMES`.

This is the "one failing test catches the drift" control that the PR comment promises but does not deliver.

---

### FIND-005 — MEDIUM — Fix in Phase 2

**CWE:** CWE-200 (Exposure of Sensitive Information)

**File:Line:** `src/connectors/observability/_anti_surveillance.py:77-83`

**Observation:**

`FORBIDDEN_SQL_COLUMNS` covers `pr.author`, `pr.author_id`, `pr.merge_by`, `pr.reviewer`, `pr.reviewers`. However, the `eng_pull_requests` schema likely also carries:
- `merged_by` (GitHub's separate "who pressed the merge button" field — distinct from `author`)
- `requested_reviewers` (JSONB array of reviewer logins — individual-identifiable)
- `pr.committer` (if present for GPG-signed commits)

Additionally, the scan uses `workers_root.glob("obs_*.py")` which correctly catches current `obs_rollup_worker.py`, but a future engineer naming a worker `observability_health_worker.py` (not matching the `obs_` prefix) would evade the scan. The glob pattern should be documented in an architectural note or the worker naming convention should be enforced via a separate test.

**Decision:** Accept for this PR; add the three missing columns and enforce the naming convention in Phase 2 as part of the Layer 4 hardening pass.

---

### FIND-006 — MEDIUM — Fix in Phase 2

**CWE:** CWE-209 (Generation of Error Message Containing Sensitive Information)

**File:Line:** `src/contexts/observability/routes.py:277, 279, 293, 330, 334, 423, 427`

**Observation:**

Multiple `HTTPException` raises use `detail=str(exc)` or `detail=f"Provider call failed: {exc}"`. The specific exceptions being stringified are:
- `UnknownProviderError`, `ProviderNotConfiguredError` — low-risk (these are application-level errors with controlled messages)
- `DatadogConnectorError` at line 293 — MEDIUM risk: this could contain an HTTP response body or status from the Datadog API, including partial authentication context

`detail=f"Provider call failed: {exc}"` at line 293 is the most concerning. If `DatadogConnectorError.__str__()` includes the upstream HTTP response body (which some httpx-based connectors do), the API key from the 401 response context could leak to the caller.

**Decision:** Low-urgency in MVP (all callers are admin operators, not tenant end-users). Fix in Phase 2 when the auth/RBAC boundary is hardened. At minimum, `DatadogConnectorError` should be audited to ensure its `__str__` does not include credentials.

---

### FIND-007 — LOW — Accept

**CWE:** CWE-200 (theoretical — Python 3.11+ only)

**File:Line:** `src/shared/exception_middleware.py:64-81`

**Observation:**

PEP 678 (Python 3.11+) allows `exception.add_note(str)` to attach notes to exceptions. The middleware logs `type(exc).__name__` only, which does not access `exc.__notes__`. The test at line 103-123 checks `record.getMessage()`, `record.args`, `record.exc_info`, `record.exc_text` — none of which would expose `__notes__` either. This is safe.

**Decision:** Accept. The deployment Python version is 3.9 (confirmed from `sys.version` check), so PEP 678 is unavailable. Note for R2 when Python version may be upgraded.

---

### FIND-008 — LOW — Accept with runbook

**CWE:** CWE-441 (Unintended Proxy or Intermediary)

**File:Line:** `scripts/rotate_obs_master_key.py:86-94`

**Observation:**

`PULSE_OBS_ROTATION_DATABASE_URL` allows an operator to point the rotation script at any postgres host. This is useful for running against a restored backup snapshot (the runbook's intended use), but it also means a compromised operator workstation could redirect rotation to an attacker-controlled host to exfiltrate plaintext API keys as they are decrypted and re-encrypted.

**Decision:** Accept. This is an administrative script requiring direct server access to run at all. The runbook should note that `PULSE_OBS_ROTATION_DATABASE_URL` must only point to a PULSE-owned postgres instance. Mitigate in R2 with Secrets Manager + IAM-restricted DB access so the script cannot be pointed externally.

---

### FIND-009 — LOW — Accept

**CWE:** CWE-400 (Uncontrolled Resource Consumption)

**File:Line:** `alembic/versions/023_obs_pii_trigger_recursive.py:81-106`

**Observation:**

The `WITH RECURSIVE` CTE in the trigger has no `MAXRECURSION` guard. PostgreSQL does enforce a default recursion depth limit (`max_cte_recursion` is absent as a parameter; recursion terminates when the recursive term produces no new rows). For non-cyclic JSONB (which valid JSONB always is — it's a tree), this terminates naturally. A deeply-nested JSONB (>500 levels) would consume stack on the postgres server before terminating, but no JSONB value can be truly cyclic (JSON spec forbids it), so the CTE always terminates.

**Decision:** Accept. The `metadata` column is populated by PULSE's own adapter code (not raw vendor input), and the Layer 1 strip has already processed it. A DoS via artificially deep JSONB is a theoretical insider threat, not a realistic external attack in this context.

---

### FIND-010 — INFORMATIONAL — Track in Phase 2

**File:Line:** `src/connectors/observability/base.py:69, 111, 144`

**Observation:**

`DeployMarker.vendor_raw`, `MonitorState.vendor_raw`, and `ServiceEntity.vendor_raw` are all typed `dict` with no schema constraint. The docstring on `DeployMarker` says "Business code MUST NOT read from it; CI lint enforces this (ADR-025 L4)" — but the Layer 4 lint only scans for `FORBIDDEN_REFS` as string literals in code. It does not prevent business code from doing `marker.vendor_raw.get("user.email")`.

The obligation that `strip_pii()` has already been applied to `vendor_raw` before the dataclass is constructed is not encoded in the type system. A future adapter could store unstripped vendor data in `vendor_raw` and business code could read it.

**Decision:** Accept for Phase 1. Track in Phase 2: consider typing `vendor_raw` as a sentinel type (e.g. `SanitizedDict`) that can only be constructed via `strip_pii()` to encode the obligation in the type system. Alternatively, add a Protocol-level docstring obligation that adapters acknowledge via a required method.

---

### FIND-011 — INFORMATIONAL — Closed

**File:Line:** `src/contexts/metrics/services/flow_health_on_demand.py:450`, `src/contexts/pipeline/routes.py:960-975`

**Observation:**

Both exceptions to the f-string SQL ban are legitimate as audited:
- `flow_health_on_demand.py:450` splices `_STATEMENT_TIMEOUT_MS` (module-level int constant `3000`); `SET LOCAL` does not accept bound params in the value position. No user input. Correct.
- `pipeline/routes.py:960-975` builds a fragment string containing only bound-param placeholders (`:s0`, `:s1`, etc. from an internal counter). User input flows in as the bound VALUE via the `params` dict, never as the SQL string itself. Correct.

The `TestNoFStringSqlInOtherSites` test correctly catches any NEW f-string SQL sites. Both exceptions are in `KNOWN_EXCEPTIONS`. Closed.

---

### FIND-012 — INFORMATIONAL — Closed

**File:Line:** `src/connectors/observability/base.py:191-249`

**Observation:**

The Protocol fix (T1.1) is architecturally correct. `@runtime_checkable` + `isinstance()` check in `test_protocol_compliance.py` means any future adapter missing `list_monitors_for_service` will fail the `isinstance` check at test time. The `REQUIRED_METHODS` frozenset in the test locks the surface so deletions are caught.

No type confusion risk from the typing approach: Python Protocol `@runtime_checkable` only checks method presence via `isinstance`, not argument/return type compatibility — so a malicious adapter could still provide wrong types. But this is the known limitation of Python structural typing and is not addressable at the Protocol level without runtime argument validation (which would be excessive overhead here). Closed.

---

## Cross-Commit Interaction Analysis

### Exception middleware + rotation script (G scenario)

If a future admin endpoint triggers rotation internally (unlikely by design — the script is a CLI), the middleware would swallow the raised exception class and return an opaque 500. This is actually CORRECT behavior for that scenario: the operator gets a request_id, can correlate with logs showing `err_class=OperationalError`, and the plaintext is not leaked. No additional risk from the combination.

### Exception middleware + `logger.exception` (FIND-001 + T1.4)

This combination is the live defect: T1.4 installs sanitization at the outer boundary, but FIND-001 shows an inner `logger.exception` bypasses it. These two commits together create a false sense of security — operators may believe the middleware covers all exception paths when it does not.

### Recursive trigger + Layer 1 strip (T1.5 + existing `_anti_surveillance.py`)

Defense-in-depth working correctly. Layer 1 removes PII before it reaches the DB. Layer 2 (recursive trigger) catches any Layer 1 miss. Both layers use the same key set (today). FIND-004 is the only gap — the sync is not mechanically enforced.

### SQL injection fix + RLS (T1.3 + existing `get_session`)

The bound-parameter form of `set_config` integrates correctly with the session factory. The type annotation (`UUID`) provides the first defense; the bound param provides the second. RLS policies (`current_setting('app.current_tenant')`) receive a string value, not SQL-injectable input, regardless of what is passed. Sound.

---

## Timing Attack Assessment

No timing-sensitive cryptographic comparisons exist in this Phase 1 code. `fingerprint()` uses SHA-256 with no comparison against stored values (the fingerprint is for auditing, not authentication). The `VALID_SITES` allowlist uses `in` (set membership) which is O(1) and does not vary with the input in a secret-dependent way. No timing attack surface introduced.

---

## Test Coverage Assessment

| Commit | Tests | Assessment |
|--------|-------|------------|
| T1.1 — Protocol fix | `test_protocol_compliance.py` (5 tests) | Adequate — covers surface lock, isinstance, DatadogProvider |
| T1.2 — Rotation script | `test_rotate_obs_master_key.py` (8 tests) | Good — covers fingerprint, env validation, dry-run, round-trip, idempotence. MISSING: test that rotation does NOT log plaintext on decrypt failure |
| T1.3 — SQL injection | `test_database_security.py` (4 tests) | Strong — signature check, source grep, mock execute assertion, hostile-input test |
| T1.4 — Exception middleware | `test_exception_middleware.py` (4 tests) | Good for the happy path. MISSING: HTTPException pass-through test (blocks FIND-003) |
| T1.5 — Recursive trigger | `test_obs_pii_trigger_recursive.py` (19 parametrized + named) | Good integration coverage. MISSING: contract test for key-list drift (FIND-004) |
| T1.6 — Layer 4 scan widen | `test_obs_anti_surveillance.py` (TestForbiddenSqlColumnsScan) | Adequate for current columns. MISSING: workers naming convention guard |

---

## Must-Fix Before Merge (Summary)

1. **FIND-001** — Replace `logger.exception` with `logger.error` (class-name only, no `exc_info`) in `routes.py:validate_datadog_credential`. This is a direct bypass of T1.4's sanitization guarantee.

2. **FIND-003** — Add `HTTPException` pass-through to `SanitizingExceptionMiddleware.dispatch()` so 4xx validation errors reach clients correctly. Add the corresponding test.

3. **FIND-004** — Add a contract test that mechanically verifies `_FORBIDDEN_KEYS` in `023_obs_pii_trigger_recursive.py` equals `FORBIDDEN_FIELD_NAMES` in `_anti_surveillance.py`. The comment claiming this is tested is false; the test does not exist.

4. **FIND-002** — Correct the module docstring in `rotate_obs_master_key.py` and the runbook to accurately describe the two-step (plaintext-in-Python-heap) architecture. No code change required.

---

## Phase 2 Review Scope (pre-merge checklist for next cycle)

The following items are out of scope for Phase 1 by design (D2 stage gate) but must be on the Phase 2 security review agenda:

- FIND-005: Widen `FORBIDDEN_SQL_COLUMNS` (merged_by, requested_reviewers, committer).
- FIND-006: Audit `DatadogConnectorError.__str__()` for credential leakage; replace `detail=str(exc)` in the observability router with sanitized messages.
- FIND-010: Evaluate `SanitizedDict` or equivalent type-system encoding of the `strip_pii` obligation on `vendor_raw`.
- Rate limiting on the admin credential validation endpoint (`POST /datadog/validate`) — no throttle currently; an attacker with network access could use it as an oracle.
- Authentication: `TenantMiddleware` is MVP-only (no JWT/RBAC). All admin endpoints are unauthenticated. This is the highest-priority Phase 2 work and blocks production deployment of any observability feature.
