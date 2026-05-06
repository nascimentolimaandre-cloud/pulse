# ADR-025: Observability Anti-surveillance Enforcement

- **Status:** Accepted
- **Date:** 2026-05-06
- **Deciders:** Main session + `pulse-ciso` + `pulse-data-scientist`
- **Related:** ADR-011 (metadata-only security), ADR-014 (Jira discovery anti-surveillance), FDD-OBS-001

---

## Context

Observability platforms are richer in **personally identifying data**
than Jira/GitHub/Jenkins:

- **Distributed tracing spans** can carry `user.id`, `user.email`,
  request payloads with PII.
- **APM metadata** often includes `deployment.author` (the dev who
  deployed) — directly attributable.
- **Alerts** sometimes embed assignee usernames, on-call schedules.
- **Service metadata** can reference engineers as service owners
  (different from squad ownership).

PULSE's **anti-surveillance principle** (ADR-011) is:

> No metric ever exposes per-developer attribution. All aggregates are
> at squad/team level minimum. Code views, code review participation,
> commit authorship, etc. are never visualized or scored.

Naively ingesting observability data **breaks this principle** in
multiple subtle ways. This ADR enforces the boundary at the schema
+ adapter + lint level.

## Decision

Apply **5 layers of defense** so anti-surveillance violation requires
deliberately breaking multiple guardrails:

### Layer 1 — Adapter strips at ingestion

Each `ObservabilityProvider` adapter (ADR-023) is responsible for
**stripping** identifying fields BEFORE returning data to PULSE
business code.

```python
# connectors/observability/_anti_surveillance.py
FORBIDDEN_FIELD_NAMES = frozenset({
    "user", "user_id", "user.id", "user.email",
    "deployment.author", "alert.assignee", "incident.assignee",
    "owner.email", "ack_by", "resolved_by", "creator", "modified_by",
    "trace.user_id", "rum.user_id",
})

def strip_pii(record: dict) -> dict:
    """Recursively remove forbidden keys from a vendor JSON record.
    Returns a copy. Logs a counter increment per stripped field."""
    ...
```

Every adapter calls `strip_pii(vendor_response)` BEFORE returning
`DeployMarker` / `MetricSeries` / `ServiceEntity`. Strip telemetry is
emitted to track which providers/tenants surface PII most often.

### Layer 2 — Schema CHECK constraints

The `obs_metric_snapshots` and `service_squad_ownership` tables have
**no columns** that could carry per-user data. We refuse to add them.

For tables that have free-form `metadata JSONB` (escape hatch from
`vendor_raw` in ADR-023), we add a database trigger:

```sql
CREATE OR REPLACE FUNCTION obs_no_pii_in_metadata() RETURNS trigger AS $$
DECLARE
    forbidden_keys TEXT[] := ARRAY[
        'user', 'user_id', 'user.email', 'deployment.author',
        'alert.assignee', 'incident.assignee', 'creator'
    ];
    k TEXT;
BEGIN
    FOREACH k IN ARRAY forbidden_keys LOOP
        IF NEW.metadata ? k THEN
            RAISE EXCEPTION 'PII key % blocked in obs metadata (ADR-025)', k;
        END IF;
    END LOOP;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER obs_metadata_pii_guard
BEFORE INSERT OR UPDATE ON service_squad_ownership
FOR EACH ROW EXECUTE FUNCTION obs_no_pii_in_metadata();
```

A failed INSERT at the DB layer is a **scream test** that surfaces
violations immediately in CI/staging, before reaching production.

### Layer 3 — Aggregate-only API responses

The route handlers for `/v1/obs/*` enforce squad/service granularity:

- `GET /v1/obs/timeline` → returns deploys aggregated to `(squad, service, hour)`.
  Forbidden response shape: any list of `(deploy, author)` tuples.
- `GET /v1/obs/ownership` → returns `service ↔ squad`. The vendor's
  `owner_email` is filtered before response serialization.
- `GET /v1/obs/incidents` → returns counts + durations per
  `(squad, service)`. The on-call's identity is dropped at the adapter.

A unit test guards each route:

```python
def test_response_has_no_pii():
    response = client.get("/v1/obs/timeline?period=30d&squad_key=OKM")
    body_str = response.text.lower()
    for forbidden in ("@", "email", "user_id", "ack_by", "assignee"):
        assert forbidden not in body_str, f"PII leaked: {forbidden}"
```

### Layer 4 — Source-grep CI lint

A test mirrored from FDD-DSH-050's anti-surveillance test scans every
file under `connectors/observability/` and `contexts/observability/`
for forbidden field references in code (not just docstrings):

```python
# tests/unit/test_obs_anti_surveillance.py
FORBIDDEN_REFS = {"user.email", "deployment.author", "alert.assignee", ...}

def test_obs_modules_contain_no_pii_references():
    for src_file in glob("src/connectors/observability/**/*.py"):
        body = strip_strings_and_comments(read(src_file))
        for ref in FORBIDDEN_REFS:
            assert ref not in body, f"{src_file} references {ref!r}"
```

Strings-and-comments stripping ensures we don't block documentation
of WHY we strip these fields. Only **code paths** can't reference them.

### Layer 5 — RLS by squad/service, never by user

Following ADR-002, all observability tables have RLS keyed on
`tenant_id`. Within a tenant, no RLS restricts BY user — because no
table has a user column. The constraint is **architectural**: there
is no user dimension in the obs schema, period.

If a future feature requests "show me incidents on-call for user X",
it requires a separate schema, separate ADR, and separate CISO sign-off.
Default position: rejected.

### Provider-specific notes

| Provider | Risk | Mitigation |
|----------|------|------------|
| **Datadog** | `service.team_email`, `events.author`, RUM `user.id`, APM `usr.email` | Strip in `datadog_connector._normalize_event()` and `_normalize_service()` |
| **New Relic** | `nrEntity.lastReportingUser`, alert `policy.creatorUser`, trace `userId` | Strip in `newrelic_connector._normalize_entity()` |
| **Grafana** | `dashboard.createdBy`, alert `silenceCreator` | Strip in R4 |
| **Honeycomb** | trace `user.email` extremely common | R4 — extra scrutiny |
| **Dynatrace** | RUM session user_id pervasive | R4 — extra scrutiny |

## Consequences

### Positive
- 5 independent layers — defeating anti-surveillance requires
  bypassing all of them. Belt-and-suspenders aligned with ADR-011.
- Database-level enforcement (Layer 2) is the most reliable; even a
  bug in the adapter can't leak PII into `obs_metric_snapshots`.
- CI lint (Layer 4) catches violations at PR time, before merge.

### Negative
- Stripping at ingestion means tenants who LEGITIMATELY want
  per-engineer attribution (some org cultures do — performance reviews
  driven by metrics) cannot opt-in. We accept this — those tenants are
  not our ICP. Documented as an explicit positioning choice.
- Adapter complexity: every new provider adds the strip logic +
  mapping. Alleviated by `strip_pii()` shared utility.
- DB triggers add ~0.5ms per INSERT. Negligible for the obs schema's
  expected write volume (rollup worker + occasional UI overrides).

## Audit & validation

- **Pre-launch**: `pulse-ciso` agent runs through every API response
  + database schema and signs off (CISO review gate, mandatory before
  R2 GA).
- **Quarterly**: automated PII-detection scan on production
  `obs_metric_snapshots` + `service_squad_ownership` (any ad-hoc
  metadata smelling like an email/UUID pattern triggers alert).
- **Tenant-facing**: `/settings/integrations/observability` page shows
  a clear note: "PULSE intentionally does not surface per-engineer
  data from your observability stack. Squads and services only."
