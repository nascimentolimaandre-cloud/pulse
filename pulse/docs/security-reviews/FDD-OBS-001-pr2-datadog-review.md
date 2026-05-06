# Security Review — FDD-OBS-001 PR 2: Datadog Connector + Admin Credentials Endpoint

**Reviewer:** PULSE-CISO  
**Date:** 2026-05-06  
**Branch:** `feat/obs-001-datadog-connector`  
**Scope:** New files only (foundation files already approved in PR 1)  
**Classification:** REAL-MONEY REVIEW — first PR to handle live customer secrets  

---

## Executive Summary

PR 2 is structurally sound. The three-layer SSRF defense (Pydantic → service allowlist → DB CHECK), pgcrypto-in-SQL encryption, and anti-surveillance wiring are all correctly implemented. No plaintext API key leaks were found in log statements or response bodies.

Seven findings are raised: zero Critical, one High, two Medium, four Low/Informational.

**The one High finding (H-001: SQLAlchemy echo leaks master key + plaintext key when `DEBUG=true`) must be fixed before merge.** The remaining six findings are accepted risk or backlog items per the R0/R1 roadmap.

---

## Findings

---

### H-001 — SQLAlchemy `echo=settings.debug` leaks `PULSE_OBS_MASTER_KEY` and plaintext API key into application logs when `DEBUG=true`

| Attribute | Value |
|-----------|-------|
| **Severity** | High |
| **CWE** | CWE-312: Cleartext Storage of Sensitive Information |
| **Decision** | MUST FIX THIS PR |
| **Scope** | `src/database.py:19`, `src/contexts/observability/services/credential_service.py:166–170` |

**Description**

`create_async_engine` is instantiated with `echo=settings.debug` (database.py line 19). When `DEBUG=true` in `.env`, SQLAlchemy logs every SQL statement and all bound parameters to stdout at the `INFO` level. The `upsert_credential` function passes `:api_key`, `:app_key`, and `:master_key` as SQLAlchemy bound parameters (credential_service.py lines 182–193). These are the three values that must never appear in logs.

With `echo=True`, a log line like the following is emitted on every upsert:

```
INFO sqlalchemy.engine.Engine [generated in 0.00012s]
{'tenant_id': '...', 'provider': 'datadog',
 'api_key': 'abcd1234...', 'app_key': None,
 'master_key': 'base64randombytes...', 'site': 'datadoghq.com', ...}
```

**Exploit scenario**

An operator legitimately sets `DEBUG=true` during a staging troubleshoot session, restarts pulse-data, and a colleague runs a validate+persist. Both the plaintext API key and the master key appear in Docker / CloudWatch logs, which are often retained longer than expected and may flow to SIEM tools with broader access.

**Recommended fix**

Replace `echo=settings.debug` with a filter that never logs bound parameters for the observability tables, or — simpler and safer — decouple SQLAlchemy echo from the application `debug` flag entirely. Use a dedicated `SQLALCHEMY_ECHO` env var that defaults to `false` regardless of `DEBUG`, and document that it must never be set to `true` in any environment that processes credentials.

Minimal fix (database.py line 16–22):

```python
engine = create_async_engine(
    settings.async_database_url,
    # NEVER use settings.debug here — debug=True would log all bound
    # parameters including plaintext credentials and the master key.
    # Use SQLALCHEMY_ECHO env var if SQL trace is needed, defaulting False.
    echo=settings.sqlalchemy_echo,   # new field, default False always
    pool_size=5,
    ...
)
```

Add `sqlalchemy_echo: bool = False` to `Settings` with a comment warning against enabling it in any environment that touches `tenant_observability_credentials`.

---

### M-001 — `provider` path parameter in `GET /{provider}/metadata` is an unvalidated free-form string

| Attribute | Value |
|-----------|-------|
| **Severity** | Medium |
| **CWE** | CWE-20: Improper Input Validation |
| **Decision** | Address in followup (R1 — before multi-provider GA) |
| **Scope** | `src/contexts/observability/routes.py:169–184` |

**Description**

The `GET /data/v1/admin/integrations/{provider}/metadata` endpoint accepts `provider` as a plain `str` path parameter with no allowlist enforcement. The value flows directly into `get_credential_metadata(tenant_id, provider)` and then into a SQL WHERE clause. The SQL is parameterized (no injection risk), and the route returns 404 for unknown providers, so there is no immediate exploitable vulnerability.

However:
1. An attacker with admin access could enumerate providers (`/metadata/foo`, `/metadata/bar`) to discover whether specific integrations are configured without authorization beyond the default tenant scope.
2. When R1 introduces per-tenant auth, the provider field should be constrained to the known set before the DB round-trip. A response timing oracle could confirm the provider set even through the 404.
3. The 404 error detail (routes.py line 184) echoes back the provider value: `f"No credential configured for provider={provider!r}."` — this is low risk now but becomes an information-disclosure vector post-R1 if callers can probe arbitrary strings.

**Recommended fix**

Replace `provider: str` with a Literal or Enum type:

```python
from typing import Literal
SupportedProvider = Literal["datadog", "newrelic"]

async def get_provider_metadata(
    provider: SupportedProvider,
    tenant_id: UUID = Depends(get_tenant_id),
) -> CredentialMetadataResponse:
```

FastAPI will reject unknown providers with 422 (Unprocessable Entity) before the SQL call, and the OpenAPI schema will enumerate valid values for the admin UI.

---

### M-002 — DSL injection via `service` name interpolation in `query_metric` metric templates

| Attribute | Value |
|-----------|-------|
| **Severity** | Medium |
| **CWE** | CWE-77: Improper Neutralization of Special Elements used in a Command |
| **Decision** | Address in followup (before PR 4 rollup worker ships) |
| **Scope** | `src/connectors/observability/datadog_connector.py:321–326` |

**Description**

The static metric DSL templates use Python `str.format()` with a `{service}` slot (datadog_connector.py line 321: `query = template.format(service=service)`). The `service` value at this call site is documented as coming from `list_services()` output (server-side, Datadog-sourced), not from direct caller input. That trust boundary is sound in PR 2 because `query_metric` is not yet exposed via any HTTP route.

However, a Datadog operator could configure a service name containing `}` brace characters that break out of the Datadog tag filter scope. Empirically tested:

```
service = "checkout}{env:prod"
template = "sum:trace.servlet.request.errors{{service:{service}}}.as_rate()"
result  → "sum:trace.servlet.request.errors{service:checkout}{env:prod}.as_rate()"
```

This is valid Datadog query syntax and would silently expand the filter scope to include all services matching `env:prod`, not just `checkout`. This does not leak credentials or give PULSE write access, but it would produce incorrect metrics.

The threat is currently contained because: (a) the service value comes from Datadog's own service catalog, not from an end-user form field; (b) `query_metric` has no HTTP route in PR 2. The exposure window opens in PR 4 when the rollup worker begins calling `query_metric` for every service in the catalog.

**Recommended fix (before PR 4 merges)**

Sanitize the service name before interpolation. Datadog service names are restricted to `[a-z0-9_.-]` by convention; enforce that before the format call:

```python
import re
_DD_SERVICE_RE = re.compile(r'^[a-zA-Z0-9_.\-]{1,200}$')

def _safe_service(service: str) -> str:
    if not _DD_SERVICE_RE.match(service):
        raise DatadogConnectorError(f"Invalid service name for DSL: {service!r}")
    return service

query = template.format(service=_safe_service(service))
```

Add a test for the `checkout}{env:prod` case.

---

### L-001 — `logger.exception(...)` inside the defensive `except Exception` block captures the full traceback, which includes `DatadogProvider.__init__` locals

| Attribute | Value |
|-----------|-------|
| **Severity** | Low |
| **CWE** | CWE-209: Generation of Error Message Containing Sensitive Information |
| **Decision** | Accept for R0 (no evidence of actual leak); add structured logging gate in R1 |
| **Scope** | `src/contexts/observability/routes.py:89–97` |

**Description**

`logger.exception(...)` (routes.py line 90) calls Python's logging with `exc_info=True`, meaning it captures and serializes the full exception traceback. The `except Exception as exc` block wraps `provider.health_check()`, which is called while `provider` is alive inside the `async with DatadogProvider(...)` context manager. `DatadogProvider.__init__` stores `self._api_key` and `self._app_key` as instance attributes.

Whether the API key appears in the traceback depends on which exception is raised. A Python `MemoryError` during async loop scheduling, for example, could cause CPython to serialize stack locals. For the common case (`httpx.ConnectError`, `httpx.TimeoutException`) there is no exposure because `health_check()` catches these and returns `False` — they never reach the `except Exception` block in routes.py. The risk is limited to truly unexpected exceptions (assertion errors, import errors, etc.).

**Why accepted for R0:** The `health_check()` contract (documented in base.py) is "non-raising for transport failures", and the implementation honors that contract. The defensive `except Exception` block is a belt-and-suspenders guard against bugs, not the primary error path. No test or log inspection revealed a realistic path to API key exposure here.

**Recommended mitigation for R1:** Replace `logger.exception(...)` with `logger.error(..., exc_info=False)` in this block and log only the exception type name (not traceback). The tenant ID and site are sufficient for diagnosis. Alternatively, install a structlog processor that scrubs fields matching `api_key|app_key|master_key` from all log records globally.

---

### L-002 — `fingerprint(body.api_key)` called on the validate-only path (persist=False) computes and returns SHA-256(api_key[:32 hex chars]) in the HTTP response body

| Attribute | Value |
|-----------|-------|
| **Severity** | Low |
| **CWE** | CWE-200: Exposure of Sensitive Information to an Unauthorized Actor |
| **Decision** | Accept — intended design, document oracle risk in ADR |
| **Scope** | `src/contexts/observability/routes.py:116` |

**Description**

When `persist=False` and validation succeeds, the endpoint returns `key_fingerprint = credential_service.fingerprint(body.api_key)` (32 hex chars of SHA-256). This is intentional: it lets the admin UI confirm "this is the same key that's already stored" without re-decrypting from the DB.

The risk is that SHA-256 with no salt is a deterministic transform. For Datadog API keys (if they are 32 lowercase hex characters as per Datadog's current format), an attacker who obtains the fingerprint could brute-force the key against a wordlist of known Datadog API key patterns. The entropy of a 32 hex character key is 128 bits, making brute-force infeasible. The risk is informational.

**If API key format is tightened to `^[0-9a-f]{32}$`** (see L-003 below), this remains true and the fingerprint can stay. If the format remains permissive (up to 512 chars), the fingerprint oracle concern is negligible.

**No action required.** Document the oracle property in ADR-021.

---

### L-003 — API key `field_validator` does not enforce Datadog's actual key format (`^[a-f0-9]{32}$`)

| Attribute | Value |
|-----------|-------|
| **Severity** | Low |
| **CWE** | CWE-20: Improper Input Validation |
| **Decision** | Accept for R0 (forward-compat rationale is valid); revisit per-provider in R1 |
| **Scope** | `src/contexts/observability/schemas.py:33–65` |

**Description**

The `api_key` validator enforces `min_length=10, max_length=512` and rejects leading/trailing whitespace (schemas.py lines 33–65). Datadog API keys are 32 lowercase hex characters. Datadog Application keys are 40 lowercase hex characters. The permissive 10–512 range accepts values that Datadog itself would reject, allowing a misconfigured key to pass schema validation and only fail at the live `/validate` HTTP probe.

The rationale for keeping it permissive is forward-compat: when New Relic (R3) or other providers reuse this schema shape, their key formats may differ (NR user keys are `NRAK-...` format, 40 chars). Per-provider validators would be cleaner.

**Recommended future action for R1:** Introduce a `provider`-discriminated schema hierarchy:

```python
class DatadogValidateRequest(BaseModel):
    api_key: str = Field(..., pattern=r'^[a-f0-9]{32}$')
    app_key: str | None = Field(default=None, pattern=r'^[a-f0-9]{40}$')
    ...
```

```python
class NewRelicValidateRequest(BaseModel):
    api_key: str = Field(..., pattern=r'^NRAK-[A-Z0-9]{27}$')
    ...
```

---

### I-001 — No authentication gate on admin endpoints (known debt, consistent with existing API posture)

| Attribute | Value |
|-----------|-------|
| **Severity** | Informational |
| **CWE** | CWE-306: Missing Authentication for Critical Function |
| **Decision** | Accept for R0 (known architectural debt); MUST be gated before R1 multi-tenant rollout |
| **Scope** | `src/contexts/observability/routes.py:62–160`, `src/shared/tenant.py:19–36` |

**Description**

`TenantMiddleware` (tenant.py lines 19–36) currently injects `settings.default_tenant_id` into every request without verifying caller identity — this is documented MVP behavior. As a consequence, any caller with network access to pulse-data can invoke `POST /admin/integrations/datadog/validate?persist=true` and store arbitrary (valid) Datadog credentials for the default tenant.

This is consistent with every other admin route in pulse-data (sync triggers, sprint refresh, etc.) and was approved as R0 technical debt in the foundation review. It is listed here because PR 2 is the first route that stores real secrets, making the exposure materially different from the rest of the admin surface.

**Pre-R1 gate requirement:** Before any R1 multi-tenant rollout, `TenantMiddleware` must be replaced by JWT verification (OAuth 2.0/OIDC, Auth0 or Cognito), and the observability admin routes must require the `admin` or `owner` RBAC role. A symbolic `Depends(require_admin_role)` stub can be added now so the injection point is already in place, even if the stub returns `True` until R1.

Adding the stub now costs one line per endpoint and makes the R1 implementation a drop-in rather than a refactor:

```python
# routes.py — add stub dependency, wired to real auth in R1
from src.shared.auth import require_admin  # stub returns True in R0

@admin_router.post("/datadog/validate", ...)
async def validate_datadog_credential(
    body: DatadogValidateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    _: None = Depends(require_admin),    # ← stub, enforced in R1
) -> DatadogValidateResponse:
```

---

### I-002 — No per-tenant rate limit on `POST /validate` (brute-force credential probing)

| Attribute | Value |
|-----------|-------|
| **Severity** | Informational |
| **CWE** | CWE-307: Improper Restriction of Excessive Authentication Attempts |
| **Decision** | Backlog to R1 (gated by auth; brute-force without auth is moot pre-auth) |
| **Scope** | `src/contexts/observability/routes.py:62` |

**Description**

`POST /admin/integrations/datadog/validate` makes a live HTTPS call to Datadog's `/api/v1/validate` endpoint on every invocation with no rate limiting. An adversary with network access (pre-R1: anyone) could submit candidate API keys at the network speed of Datadog's response time (~200ms/call), effectively using PULSE as a Datadog credential oracle at ~5 req/sec.

**Why deferred to R1:** The absence of authentication (I-001) means that adding rate limiting now creates an illusion of security. The correct ordering is: ship auth first (R1), then add per-tenant rate limiting on the authenticate-gated path. In R1, `slowapi` with a per-tenant bucket of 10 req/min on this endpoint is the recommended implementation. Document this in the R1 security backlog (FDD-CISO-001).

---

## Specific Questions from the PR Author

**1. Plaintext leak vectors — log grep result**

All `logger.*` calls in the three PR 2 files were reviewed. None log `api_key`, `app_key`, or `master_key` values. The only log lines touching secrets are:

- `credential_service.py:197–200` — logs `fingerprint[:8]` (8 hex chars, not the key). Safe.
- `routes.py:149–152` — logs `stored.key_fingerprint[:8]`. Safe.
- `routes.py:90–97` — `logger.exception(...)` raises the traceback concern addressed in L-001 above.
- `datadog_connector.py:148–162` — logs `type(exc).__name__` and `self._site` only. Safe.

**H-001** (the `echo=settings.debug` path via SQLAlchemy) is the one real leak vector found, and it is the only must-fix item.

**2. SSRF — service interpolation trust boundary**

The `service` value in `query_metric` originates from `list_services()`, which queries Datadog's own service catalog. This is a server-side trust boundary: PULSE never accepts a service name directly from an HTTP caller in PR 2. The risk is documented as M-002 (DSL injection via malformed service name) and is contingent on a Datadog service being misconfigured with special characters — which Datadog's own validation should prevent but is not guaranteed. No action needed before PR 4.

**3. Admin endpoint auth gate**

Addressed in I-001. The recommendation is to add a `Depends(require_admin)` stub now (one-line-per-endpoint) so R1 auth is a drop-in, not a refactor. This is a soft recommendation, not a must-fix for this PR, given that all other admin routes in pulse-data have the same posture.

**4. Error detail on `503 "Could not reach Datadog."`**

The current string (`"Could not reach Datadog. Check site/network and try again."`) is acceptable. It leaks only the vendor name (not the site URL, not the key). A more terse `"Upstream service unavailable."` would be fractionally better for a multi-tenant SaaS, but for the current single-tenant R0 operator audience, the actionable hint is valuable. No change required.

**5. Persist-only-after-validate flow**

Confirmed correct. Reading routes.py lines 82–129:

1. `DatadogProvider` is constructed with the plaintext key and enters an `async with` block (lines 82–86).
2. `health_check()` is awaited (line 88). If it raises, 503 is returned before any persistence.
3. The `async with` block exits at line 98 (after `if not ok` is evaluated), calling `provider.aclose()` — the httpx client is closed and the `self._api_key` reference on the provider object is garbage-eligible.
4. Only if `ok is True` and `body.persist is True` does `upsert_credential()` run (lines 121–130).
5. The plaintext key in `body.api_key` lives for the duration of the request (FastAPI does not zero-out Pydantic model memory), but it is never written to any log or persistent store in a plaintext form at any step.

The persist-only-after-validate contract is correctly implemented.

**6. Rate limiting**

See I-002. Deferred to R1, gated behind authentication.

**7. API key format strictness (`^[0-9a-f]{32}$` vs 10–512 permissive)**

See L-003. The permissive range is accepted for R0 forward-compat. Tighten per-provider in R1 when the schema hierarchy is split.

---

## Findings Summary Table

| ID | Severity | Title | Decision |
|----|----------|-------|----------|
| H-001 | High | SQLAlchemy `echo=debug` leaks master key + plaintext key into logs | MUST FIX THIS PR |
| M-001 | Medium | Unvalidated `provider` path parameter in GET metadata | Followup R1 |
| M-002 | Medium | DSL injection via malformed service name in `query_metric` | Followup before PR 4 |
| L-001 | Low | `logger.exception` may capture `DatadogProvider` locals in traceback | Accept R0, gate R1 |
| L-002 | Low | Fingerprint oracle in validate-only response (non-brute-forceable) | Accept, document |
| L-003 | Low | Permissive API key validator (10–512) vs Datadog 32-hex format | Accept R0, tighten R1 |
| I-001 | Info | No auth gate on admin endpoints (known R0 debt) | Add stub dep now; enforce R1 |
| I-002 | Info | No rate limit on `/validate` endpoint | Backlog R1 post-auth |

---

## What Is Well Done (Do Not Change)

- **Triple-layer SSRF defense** (Pydantic → `_ensure_valid_site` → DB CHECK): correctly implemented and independently tested. The DB constraint in migration 020 as a last-resort backstop is exactly the right pattern.
- **pgcrypto-in-SQL encryption**: master key never interpolated into SQL text (always a bound parameter). Encryption and decryption happen inside Postgres, not in Python heap. `vendor_raw: {}` on all normalized dataclasses prevents unmapped Datadog fields from persisting.
- **`triggered_by = None` unconditional anti-surveillance**: enforced in the dataclass and tested. The `usr.*` nested dict fix (M-001 from foundation review) is correctly wired.
- **`DatadogProvider` per-request instantiation**: the connector is never module-global; it is created and destroyed within the `async with` block of each request. This limits the window during which the plaintext key lives on the heap.
- **`key_fingerprint[:8]` in logs** (not the full 32-char fingerprint, and certainly not the plaintext): correct operational logging practice.
- **`follow_redirects=False`** on the httpx client: prevents an attacker from redirecting the Datadog API call to an exfiltration server via HTTP redirect.
- **RLS on `tenant_observability_credentials`** (migration 017): all four DML operations are covered by tenant-scoped policies. `get_session` correctly sets `app.current_tenant` before every query.
- **Test coverage**: 46 tests (17 + 19 + 10) cover all the security-critical paths. The `SECRET_KEY not in str(body)` assertions in `test_admin_routes.py` are the right kind of test for a credentials endpoint.
