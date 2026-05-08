# ADR-028 — Observability Rollup Worker: master-key residence + log redaction

**Status**: Accepted
**Date**: 2026-05-08
**Supersedes**: nothing (extends ADR-021 + ADR-025)
**Context**: FDD-OBS-001 PR 4a

## Context

PR 4a introduces `obs_rollup_worker`, a long-running container that
queries Datadog every 15 minutes for every tenant. Two security
characteristics differ from the request-scoped admin endpoints
already shipped (PR 2):

1. **Process lifetime** — the worker stays up for hours-to-days. Any
   in-memory plaintext (master key, decrypted DD credentials, returned
   metric series) lives longer than a single HTTP request.
2. **Log volume** — at scale (Webmotors: 473 services × 6 metrics ×
   96 cycles/day = ~272k log events/day), per-call logs add up. Any
   leak at this volume is noisy.

Both warrant explicit guarantees rather than relying on the default
"every code path eventually exits".

## Decision

### 1. Master-key residence ≤ one cycle

`PULSE_OBS_MASTER_KEY` is read from `os.environ` at process start
(via Pydantic `Settings` — already done by `credential_service`). The
value is held by the `Settings` singleton for the worker's lifetime.

Per-tenant decrypted credentials (DD API key + App key) are loaded
fresh **at the start of each tenant's cycle** via `provider_factory.
build_for_tenant`, used to construct an `ObservabilityProvider`, and
the provider is **closed before moving to the next tenant** (via
`async with provider:`).

This means any individual decrypted plaintext lives in memory ≤
one cycle's duration (max ~12 minutes — the per-cycle deadline).

> **Why not also rotate the master key per cycle?** The master key is
> the KEK; rotating it requires re-encrypting every per-tenant blob,
> a coordinated migration not in PR 4a's scope. Mitigation lives in
> **RISK-1** (R4 KMS migration) — at that point the master key moves
> behind AWS KMS, and the worker calls KMS::Decrypt per tenant
> instead of holding the KEK itself.

### 2. Provider instances are NEVER cached across cycles

The architect-validated rule: `provider_factory.build_for_tenant` runs
on every cycle, even when the same tenant appeared last cycle. Caching
providers would (a) hold the decrypted plaintext for the cache
lifetime, (b) miss credential rotations, (c) keep `httpx.AsyncClient`
connections that may have stale TLS state.

Cost: rebuilding 1 `httpx.AsyncClient` + 1 `pgp_sym_decrypt` per
tenant per cycle. Webmotors at 1 tenant pays microseconds per cycle.
At R1 SaaS (10–100 tenants per pod), still sub-second overhead per
cycle — acceptable for the hardening payoff.

### 3. Service-name redaction in logs

DD service names can leak customer-naming conventions when worker logs
ship to shared infrastructure (CloudWatch group used by multiple
services, log aggregator with broad read access). Examples in real DD
catalogs: `payments-acme-customer-data-sync`, `partner-X-invoice-job`.

**Rule**: per-service log lines (`[rollup] query_metric ...`,
`[rollup] rate-limited ...`) include only `svc_hash =
sha256(service_name)[:8]`. Counts and squad keys are safe and stay
plaintext. Implemented as `_hash_service_name` in `rollup_service.py`.

The hash is **stable per name** so per-service issues stay traceable —
an operator running a one-off debug query can hash a known service
name to find its log lines.

### 4. Bound parameters in SQL exception logs (revisited)

H-002 (PR 2 review) wired `hide_parameters=True` on the SQLAlchemy
engine — that already covers the worker since the worker shares
`src.database.engine`. No new mitigation needed in this ADR.

### 5. Log levels

- `INFO` — cycle summary, per-tenant summary (counts only).
- `WARNING` — rate-limited, query_metric error, missing creds, kill switch hit.
- `ERROR` — unexpected exceptions (caught by `_run_one_cycle` wrapper).
- `DEBUG` — per-call timing (off by default; enabled via `LOG_LEVEL=DEBUG`
  for short troubleshooting windows ONLY — DEBUG also includes svc_hash,
  not raw service name).

## Consequences

**Positive**

- Master-key blast radius bounded to ≤12 min memory residence (vs
  worker uptime, which is hours).
- Service-name leaks via shared log infra mitigated; debugging by
  hash still works.
- Sets the precedent for future workers (NR/Grafana adapters) — same
  rules apply.

**Negative**

- Log lines are slightly less readable on first inspection — operators
  need to hash a service name to grep for it. Mitigation: include a
  one-line hash example in the runbook when PR 4a ships.
- Marginal CPU per cycle from `provider_factory.build_for_tenant`
  rebuilding (still acceptable per §2 above).

## Verification

Two regression tests guard the contract:

1. `test_rollup_service.py::TestServiceNameHash` — hash is sha256[:8]
   and stable.
2. `test_rollup_service.py::test_run_cycle_processes_all_tenants_when_bucket_unlimited`
   — verifies `provider_factory.build_for_tenant` is called for **every**
   tenant per cycle (no caching).

A grep-style CI lint (future addition, RISK-12) could enforce that
log statements in `rollup_service.py` never reference `service_name`
directly — only `_hash_service_name(service_name)`. Punted to backlog
because the test suite already catches the obvious cases.

## References

- ADR-021 — pgcrypto encryption + master key sourcing
- ADR-024 — Hybrid cache strategy (rollup table)
- ADR-025 — Anti-surveillance (Layer 1–4)
- FDD-OBS-001-RISK-1 — R4 KMS migration (master key blast radius)
