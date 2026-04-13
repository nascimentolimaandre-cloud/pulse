# Security Review — ADR-014: Dynamic Jira Project Discovery

**Review date:** 2026-04-13
**Reviewer:** pulse-ciso
**Branch:** feat/jira-dynamic-discovery
**Risk rating:** Medium (was High before applied fixes)

---

## Scope

Files reviewed:

- `pulse/packages/pulse-data/alembic/versions/006_jira_discovery.py`
- `pulse/packages/pulse-data/src/contexts/integrations/jira/discovery/guardrails.py`
- `pulse/packages/pulse-data/src/contexts/integrations/jira/discovery/mode_resolver.py`
- `pulse/packages/pulse-data/src/contexts/integrations/jira/discovery/project_discovery_service.py`
- `pulse/packages/pulse-data/src/contexts/integrations/jira/discovery/repository.py`
- `pulse/packages/pulse-data/src/contexts/integrations/jira/discovery/smart_prioritizer.py`
- `pulse/packages/pulse-data/src/workers/discovery_scheduler.py`
- `pulse/packages/pulse-data/src/config.py`
- `pulse/packages/pulse-api/src/modules/integrations/jira-admin/jira-admin.controller.ts`
- `pulse/packages/pulse-api/src/modules/integrations/jira-admin/jira-admin.service.ts`
- `pulse/packages/pulse-api/src/modules/integrations/jira-admin/guards/admin-role.guard.ts`
- `pulse/packages/pulse-api/src/modules/integrations/jira-admin/dto/update-config.dto.ts`
- `pulse/packages/pulse-api/src/modules/integrations/jira-admin/dto/project-action.dto.ts`
- `pulse/packages/pulse-api/src/modules/integrations/jira-admin/dto/list-query.dto.ts`
- `pulse/packages/pulse-api/src/config/env.validation.ts`
- `pulse/packages/pulse-web/src/routes/_dashboard/settings/integrations/jira.tsx`
- `pulse/packages/pulse-web/src/routes/_dashboard/settings/integrations/jira.config.tsx`
- `pulse/packages/pulse-web/src/routes/_dashboard/settings/integrations/jira.catalog.tsx`
- `pulse/packages/pulse-web/src/routes/_dashboard/settings/integrations/jira.audit.tsx`
- `pulse/packages/pulse-web/src/routes/_dashboard/settings/integrations/_components/mode-selector.tsx`
- `pulse/packages/pulse-web/src/routes/_dashboard/settings/integrations/_components/project-row-actions.tsx`

---

## Critical (block release)

None identified.

---

## High

### H-001: Timing oracle on `X-Internal-Token` comparison
**File:** `pulse/packages/pulse-data/src/workers/discovery_scheduler.py`, line 64 (pre-fix)
**Status:** FIXED in this review

The original comparison `x_internal_token != expected` is a Python string equality check that short-circuits on the first differing byte. An attacker with the ability to send many requests and measure response latencies (timing side-channel) could reconstruct the shared secret one byte at a time.

**Fix applied:** Replaced with `hmac.compare_digest(x_internal_token.encode(), expected.encode())`, which runs in constant time regardless of where the strings diverge. The `None` check was also moved inside the constant-time path — previously `None` would bypass the comparison entirely and fall through to the `!=` check (which would always fail), but now `None` is explicitly rejected first.

**Verification:** 59 Python unit tests passed after fix.

---

### H-002: `INTERNAL_API_TOKEN` not required in production
**File:** `pulse/packages/pulse-api/src/config/env.validation.ts`, line 43 — `pulse/packages/pulse-data/src/config.py`, line 51
**Status:** DEFERRED (architectural — flag)

Both services default `INTERNAL_API_TOKEN` / `internal_api_token` to an empty string. The scheduler in `discovery_scheduler.py` treats an empty expected token as "dev mode — allow all". There is no enforcement that prevents deploying to production with this token unset.

**Risk:** In production, any process that can reach the discovery scheduler port (8001) can trigger a discovery run for any tenant without authentication.

**Proposed fix:** Add a production guard in `env.validation.ts`:
```typescript
INTERNAL_API_TOKEN: z
  .string()
  .refine(
    (val) => process.env['NODE_ENV'] !== 'production' || val.length >= 32,
    'INTERNAL_API_TOKEN must be at least 32 characters in production',
  ),
```
And in `config.py`:
```python
@model_validator(mode='after')
def require_token_in_production(self) -> 'Settings':
    import os
    if os.getenv('NODE_ENV') == 'production' and not self.internal_api_token:
        raise ValueError('INTERNAL_API_TOKEN is required in production')
    return self
```
This is deferred because it requires coordination with the deployment environment setup — it is not a trivial change to the file.

---

### H-003: `sortBy` and `sortDir` string-interpolated into SQL without server-side allowlist
**File:** `pulse/packages/pulse-api/src/modules/integrations/jira-admin/jira-admin.service.ts`, line 262–264 (pre-fix)
**Status:** FIXED in this review

`query.sortBy` and `query.sortDir` were interpolated directly into the SQL `ORDER BY` clause as string template literals:
```typescript
const orderBy = `ORDER BY ${sortField} ${sortDir}`;
```

The DTO validators (`@IsIn(...)`) provide validation at the HTTP boundary, but only when the global `ValidationPipe` is active. If the pipe is absent, misconfigured, or the method is called internally, the sort parameters become a raw SQL injection vector.

**Fix applied:** Added server-side allowlist checks in the service before interpolation:
```typescript
const ALLOWED_SORT_FIELDS = new Set(['project_key', 'pr_reference_count', 'issue_count', 'last_sync_at']);
const ALLOWED_SORT_DIRS = new Set(['asc', 'desc']);
```
Unrecognised values fall back to safe defaults (`project_key asc`).

**Verification:** 34 NestJS tests passed after fix.

---

### H-004: `project_key` path parameter unvalidated at service boundary
**File:** `pulse/packages/pulse-api/src/modules/integrations/jira-admin/jira-admin.service.ts`, `getProject` and `changeProjectStatus` (pre-fix)
**Status:** FIXED in this review

The `:key` path parameter was accepted as any arbitrary string. While downstream queries use parameterised placeholders (safe from SQL injection), the value is embedded in error messages, audit log entries (`project_key` column), and returned in API responses. A crafted key such as `'; DROP TABLE jira_project_catalog; --` or a very long string could cause unexpected behaviour in logging or audit display.

**Fix applied:** Added `validateProjectKey(projectKey)` private method enforcing `^[A-Z][A-Z0-9]+$` (Jira's canonical format), called at the start of both `getProject` and `changeProjectStatus`. Returns `400 Bad Request` on violation.

**Verification:** 34 NestJS tests passed after fix.

---

## Medium

### M-001: Audit table `DO INSTEAD NOTHING` rule — silent swallow vs. raising trigger
**File:** `pulse/packages/pulse-data/alembic/versions/006_jira_discovery.py`, lines 220–225
**Status:** DEFERRED (architectural tradeoff — flag)

The migration uses PostgreSQL RULEs to make `jira_discovery_audit` append-only:
```sql
CREATE RULE no_update_audit AS ON UPDATE TO "jira_discovery_audit" DO INSTEAD NOTHING;
CREATE RULE no_delete_audit AS ON DELETE TO "jira_discovery_audit" DO INSTEAD NOTHING;
```

The `DO INSTEAD NOTHING` pattern silently discards UPDATE and DELETE operations — the caller receives success (0 rows affected) without error. This means:
- A misconfigured application that attempts to UPDATE an audit row will silently succeed without corrupting data.
- A deliberate insider attempting audit tampering receives no error feedback, making the tampering undetectable from the application layer.

**Risk assessment:** The RLS policies independently block cross-tenant access. The RULE prevents the operation but does not raise an alarm. A `BEFORE` trigger that raises `RAISE EXCEPTION 'audit rows are immutable'` would make tampering attempts visible in application logs and PostgreSQL logs.

**Proposed fix (deferred — requires new migration):**
```sql
CREATE OR REPLACE FUNCTION fn_audit_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'jira_discovery_audit rows are immutable — tampering attempt logged';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tg_audit_no_update
  BEFORE UPDATE ON jira_discovery_audit FOR EACH ROW EXECUTE FUNCTION fn_audit_immutable();

CREATE TRIGGER tg_audit_no_delete
  BEFORE DELETE ON jira_discovery_audit FOR EACH ROW EXECUTE FUNCTION fn_audit_immutable();
```
This requires replacing the RULE pattern with triggers in a subsequent migration. Flag for R1.

---

### M-002: `SET LOCAL app.current_tenant` uses string interpolation instead of parameterisation
**File:** `pulse/packages/pulse-api/src/modules/integrations/jira-admin/jira-admin.service.ts`, line 61
**Status:** DEFERRED (low exploitability given upstream guard)

```typescript
await qr.query(`SET LOCAL app.current_tenant = '${tenantId}'`);
```

`SET LOCAL` does not support parameterised placeholders in PostgreSQL, so direct interpolation is unavoidable at the TypeORM QueryRunner level. The `tenantId` value originates from `TenantGuard`, which in MVP assigns either a header-supplied value or the default UUID. The risk is that if `TenantGuard` is ever bypassed or allows arbitrary strings, an attacker could inject a malformed setting string.

**Proposed fix:** Validate `tenantId` is a valid UUID before calling `withTenant`. Add at the top of `withTenant`:
```typescript
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
if (!UUID_RE.test(tenantId)) {
  throw new BadRequestException(`Invalid tenant ID format: ${tenantId}`);
}
```
Deferred because exploitability is low today — `TenantGuard` controls the input — but this is a latent risk as the auth layer evolves.

---

### M-003: `AdminRoleGuard` accepts the generic `'admin'` role string, not only `'tenant_admin'`
**File:** `pulse/packages/pulse-api/src/modules/integrations/jira-admin/guards/admin-role.guard.ts`, line 43
**Status:** DEFERRED (intentional MVP simplification — document)

```typescript
const isAdmin = roles.includes('tenant_admin') || roles.includes('admin');
```

The guard accepts both `tenant_admin` (production RBAC role) and the generic `admin` (MVP stub role). In a multi-tenant SaaS context, a role named `admin` should not exist as an unscoped privilege. When OAuth/OIDC and RBAC are implemented in R1, all role checks must be migrated to `tenant_admin` exclusively, and the `admin` fallback removed.

**Action required at R1:** Remove `|| roles.includes('admin')` and ensure JWT claims always carry `tenant_admin` for privileged users.

---

### M-004: No rate limiting on `POST /discovery/trigger`
**File:** `pulse/packages/pulse-api/src/modules/integrations/jira-admin/jira-admin.controller.ts`, line 125
**Status:** DEFERRED (requires ThrottlerModule — flag)

`POST /admin/integrations/jira/discovery/trigger` is protected only by `AdminRoleGuard`. A tenant admin who knows their credentials can spam this endpoint, triggering a new discovery run per request. Each run calls the Jira API, runs database scans, and executes guardrail logic — enough to create a DoS against the Jira API rate limit and internal services.

No global `ThrottlerModule` or per-endpoint `@Throttle()` decorator exists in `pulse-api`.

**Proposed fix:** Register `@nestjs/throttler` globally (or per-module) with conservative limits for admin mutation endpoints:
```typescript
@Throttle({ default: { limit: 5, ttl: 60000 } })
@Post('discovery/trigger')
triggerDiscovery(...)
```
Rate: 5 triggers per minute per tenant. Deferred pending ThrottlerModule setup.

---

### M-005: `INTERNAL_API_TOKEN` sent by `pulse-api` only when non-empty
**File:** `pulse/packages/pulse-api/src/modules/integrations/jira-admin/jira-admin.service.ts`, line 415–418

```typescript
...(token ? { 'X-Internal-Token': token } : {}),
```

If `INTERNAL_API_TOKEN` is empty in `pulse-api`, the header is omitted entirely. Combined with H-002 (scheduler allows empty token in dev), this creates a configuration state where production services can talk to each other without any authentication token being transmitted. This is already captured under H-002 but worth noting as a distinct configuration risk.

---

## Low

### L-001: PII regex warning on discovered project names is absent (ADR-014 mandated gap)
**Files:** `pulse/packages/pulse-data/src/contexts/integrations/jira/discovery/project_discovery_service.py` — `pulse/packages/pulse-web/src/routes/_dashboard/settings/integrations/_components/`
**Status:** GAP — flag for engineer to implement

ADR-014 mandated a PII warning for discovered projects whose name matches sensitive patterns ("HR", "legal", "finance", "confidential"). Neither `ProjectDiscoveryService.run_discovery` nor the UI catalog components contain this check. Projects with sensitive names are silently discovered and can be auto-activated in `auto` or `smart` mode.

**Proposed fix (backend — in `project_discovery_service.py`):**
```python
import re
_PII_PATTERN = re.compile(r'\b(hr|human.?resources|legal|finance|payroll|confidential|gdpr|pii)\b', re.IGNORECASE)

def _is_pii_sensitive(name: str | None) -> bool:
    return bool(name and _PII_PATTERN.search(name))
```
When `_is_pii_sensitive(jp.get("name"))` is `True`, the project should be inserted with `status="discovered"` (not `"active"`) regardless of mode, and an audit event `"pii_warning_flagged"` should be written.

**Proposed fix (UI — in `project-catalog-table.tsx` or similar):** Display a warning badge on rows where the project name matches the sensitive pattern client-side, prompting the admin to review before activating.

This is flagged as Low rather than High because `blocked` is always honoured and a human admin must activate in `allowlist` mode. However, in `auto` or `smart` mode, HR/legal projects will be ingested without warning — which the ADR explicitly prohibited.

---

### L-002: Audit CSV export includes raw `actor` field (internal user ID, not display name)
**File:** `pulse/packages/pulse-web/src/routes/_dashboard/settings/integrations/jira.audit.tsx`, line 99
**Status:** Informational — acceptable for MVP

The audit CSV export writes `entry.actor` directly. In MVP, actor is a user UUID (`req.user.id`). In R1 with OIDC, this could become an email address. Confirm in R1 that email addresses in the audit log are handled according to LGPD/GDPR data minimisation requirements (use user ID, not email).

---

### L-003: `tenant_jira_config.last_discovery_status` column length is 16 chars; `discovery_status` values may exceed this
**File:** `pulse/packages/pulse-data/alembic/versions/006_jira_discovery.py`, line 89
**Status:** Low — potential data truncation

`last_discovery_status` is `String(16)`. The possible values written are `"success"`, `"failed"`, `"partial"` — all within 16 chars. However, if the value set expands (e.g., `"partial_timeout"` = 15 chars, still OK) a future developer could silently truncate. Consider increasing to `String(32)` for headroom. No fix applied — trivial migration concern.

---

### L-004: `discovery_scheduler.py` binds the internal API on `0.0.0.0:8001`
**File:** `pulse/packages/pulse-data/src/workers/discovery_scheduler.py`, line 205

```python
config = uvicorn.Config(trigger_app, host="0.0.0.0", port=8001, log_level="info")
```

In production, this internal endpoint should be bound to `127.0.0.1` or a VPC-internal interface only. Binding to `0.0.0.0` exposes port 8001 to all network interfaces, including any public-facing interface on the host. In the Docker Compose dev setup this is acceptable; in production (ECS Fargate or Lambda), ensure the security group / VPC configuration blocks external access to port 8001. The token check (H-001, now fixed) is the last line of defence if this is inadvertently exposed.

---

## Informational

### I-001: RLS on `jira_discovery_audit` — UPDATE/DELETE policies exist but are rendered unreachable by the RULE
**File:** `pulse/packages/pulse-data/alembic/versions/006_jira_discovery.py`

`_enable_rls` creates UPDATE and DELETE RLS policies for the audit table. These are correct as a belt-and-suspenders measure. However, the `DO INSTEAD NOTHING` RULE fires before RLS evaluation in PostgreSQL's rule processing order, so the RLS UPDATE/DELETE policies are unreachable in practice. They are not harmful — just dead code. When the RULE is replaced by a trigger (M-001), the trigger fires after RLS, so the RLS policies will become meaningful. No change needed now.

---

### I-002: `DYNAMIC_JIRA_DISCOVERY_ENABLED` default is `False` — correct
**File:** `pulse/packages/pulse-data/src/config.py`, line 50

The feature flag defaults to `False` (shadow mode). This is the correct posture per ADR-014. Confirmed.

---

### I-003: All repository queries filter by `tenant_id` explicitly — confirmed
**File:** `pulse/packages/pulse-data/src/contexts/integrations/jira/discovery/repository.py`

Every `SELECT`, `UPDATE`, and `INSERT` in `DiscoveryRepository` includes an explicit `tenant_id == tenant_id` predicate in addition to RLS. Belt-and-suspenders pattern confirmed throughout. No gaps found.

---

### I-004: `blocked` invariant upheld in Guardrails — confirmed
**File:** `pulse/packages/pulse-data/src/contexts/integrations/jira/discovery/guardrails.py`

`record_sync_outcome` (line 214) checks `project["status"] == "blocked"` and returns early — blocked projects are never modified automatically. `enforce_project_cap` selects only `status == "active"` projects for pausing — blocked projects are excluded because their status is not `"active"`. `ModeResolver._resolve_smart` explicitly filters `status != "blocked"`. Invariant confirmed across all three code paths.

---

### I-005: Redis rate bucket keys include `tenant_id` — confirmed
**File:** `pulse/packages/pulse-data/src/contexts/integrations/jira/discovery/guardrails.py`, line 139

```python
bucket_key = f"jira:ratebudget:{tenant_id}"
```

Tenant scope is included in the Redis key. Cross-tenant budget contamination is not possible. Confirmed.

---

### I-006: Status transition validation is strict — confirmed
**File:** `pulse/packages/pulse-api/src/modules/integrations/jira-admin/jira-admin.service.ts`, lines 28–33

`STATUS_TRANSITIONS` explicitly lists valid `from` states for each action. `changeProjectStatus` checks `transition.from.includes(currentStatus)` and raises `400 Bad Request` on invalid transitions. The service tests include a regression for "pause from discovered" being rejected. Confirmed.

---

### I-007: All mutations write an audit row with `actor = req.user.id` — confirmed
**File:** `pulse/packages/pulse-api/src/modules/integrations/jira-admin/jira-admin.service.ts`

`changeProjectStatus` passes `actorId` (from `req.user.id` via `@CurrentUser()`) to the audit INSERT. `updateConfig` does the same when mode changes. System-initiated changes (guardrails, auto-pause) use `actor="system"` — this is semantically correct. Confirmed.

---

### I-008: No sensitive data rendered in plaintext in UI — confirmed
**Files:** `jira.audit.tsx`, `jira.catalog.tsx`, `jira.config.tsx`

Jira API tokens are not stored in these tables and are not surfaced in any UI component reviewed. The audit display shows `entry.actor` (a user ID / "system") — not email addresses or tokens. Confirmed for MVP.

---

### I-09: Audit CSV export is client-side only from API-returned data — confirmed
**File:** `pulse/packages/pulse-web/src/routes/_dashboard/settings/integrations/jira.audit.tsx`, line 92

The CSV export operates on `data.items` — the current paginated response from the API. It does not make additional API calls or access browser storage from other tenants. Cross-session data leakage is not possible. Confirmed.

---

### I-010: Block action has no confirmation dialog
**File:** `pulse/packages/pulse-web/src/routes/_dashboard/settings/integrations/_components/project-row-actions.tsx`

The "block" action in `ProjectRowActions` fires `mutation.mutate({ action, projectKey })` immediately on click, with no confirmation dialog. Per the review scope, destructive operations (block especially) should require confirmation. This is a UX security control, not a backend vulnerability. Flag for frontend to add a confirm dialog before the `mutate` call on `'block'` action.

---

## Summary of Findings by Severity

| ID | Severity | Title | Status |
|----|----------|-------|--------|
| H-001 | High | Timing oracle on X-Internal-Token | FIXED |
| H-002 | High | INTERNAL_API_TOKEN not required in production | DEFERRED |
| H-003 | High | sortBy/sortDir SQL injection risk | FIXED |
| H-004 | High | project_key path param unvalidated | FIXED |
| M-001 | Medium | Audit table RULE swallows tampering silently | DEFERRED |
| M-002 | Medium | SET LOCAL uses string interpolation | DEFERRED |
| M-003 | Medium | AdminRoleGuard accepts generic 'admin' role | DEFERRED (R1) |
| M-004 | Medium | No rate limiting on discovery trigger | DEFERRED |
| M-005 | Medium | Token omitted when empty in API proxy | Covered by H-002 |
| L-001 | Low | PII regex warning missing (ADR-014 gap) | DEFERRED (engineer) |
| L-002 | Low | Audit CSV actor field may expose email in R1 | Note for R1 |
| L-003 | Low | last_discovery_status column too narrow | Trivial migration |
| L-004 | Low | Scheduler binds to 0.0.0.0 | Infra config |
| I-001–I-010 | Info | Various confirmations and notes | Confirmed |

---

## Fixes Applied

| Fix | File | Change |
|-----|------|--------|
| H-001 | `pulse/packages/pulse-data/src/workers/discovery_scheduler.py` | Replaced `!=` string comparison with `hmac.compare_digest()`. Added explicit `None` check before comparison. |
| H-003 | `pulse/packages/pulse-api/src/modules/integrations/jira-admin/jira-admin.service.ts` | Added server-side `ALLOWED_SORT_FIELDS` and `ALLOWED_SORT_DIRS` Set lookups before interpolation in `listProjects`. |
| H-004 | `pulse/packages/pulse-api/src/modules/integrations/jira-admin/jira-admin.service.ts` | Added `validateProjectKey()` private method enforcing `^[A-Z][A-Z0-9]+$`. Called at entry of `getProject` and `changeProjectStatus`. |

## Fixes Deferred

| Fix | File | Reason |
|-----|------|--------|
| H-002 | `env.validation.ts` + `config.py` | Requires deployment environment coordination — not a trivial code change. Must be implemented before R1 production deployment. |
| M-001 | `006_jira_discovery.py` | Requires a new migration (007) to replace RULE with BEFORE trigger. Architectural change. |
| M-002 | `jira-admin.service.ts` | Low exploitability today; MVP auth guard controls input. Implement UUID validation in `withTenant` during R1 auth hardening. |
| M-003 | `admin-role.guard.ts` | Intentional MVP simplification. Remove `'admin'` fallback when OIDC roles are implemented in R1. |
| M-004 | `jira-admin.controller.ts` | Requires ThrottlerModule registration in app root. Implement as part of global rate limiting story in R1. |
| L-001 | `project_discovery_service.py` + UI | ADR-014 gap. Assign to pulse-data-engineer + pulse-frontend to implement PII regex check before auto-activation. Required before enabling `auto` mode in production. |
| L-002 | `jira.audit.tsx` | Note for R1 — confirm actor field does not expose email under LGPD. |
| I-010 | `project-row-actions.tsx` | Confirmation dialog for block action — assign to pulse-frontend. |

---

## Risk Rating

**Current (after applied fixes): Medium**

Justification:
- The three High findings that were trivially fixable (timing attack, SQL injection via sort, path param injection) are now resolved and test suites confirm no regressions.
- The remaining High finding (H-002: production token enforcement) is a configuration risk, not a code defect, and is Low likelihood in a controlled deployment.
- The Medium findings (audit tamper observability, tenant ID interpolation, generic admin role, rate limiting) are real but have compensating controls: RLS prevents cross-tenant access even if the RULE swallows tampering, `TenantGuard` controls tenant ID input today, the admin role is tightly controlled in MVP, and discovery trigger spam is limited by Jira API rate limits.
- The L-001 PII gap is the most operationally relevant: it must be resolved before enabling `auto` or `smart` mode in production, because those modes auto-activate projects without human review.

**The implementation is safe to release to staging with `DYNAMIC_JIRA_DISCOVERY_ENABLED=False` (shadow mode). It must not be enabled in production with `auto` or `smart` mode until H-002 and L-001 are resolved.**
