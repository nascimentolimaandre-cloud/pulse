"""FDD-OBS-001 — Observability connector adapters.

Each provider (Datadog, New Relic, Grafana, ...) implements the
`ObservabilityProvider` Protocol from `base.py`. Vendor-specific
query translation, tag normalization, rate-limit handling, and
PII stripping live ENTIRELY inside the adapter — business code
in `contexts/observability/` never sees vendor JSON.

PR 1 ships only the Protocol + dataclasses. PR 2 adds
`datadog_connector.py`. PR 3+ adds NR / Grafana etc.
"""
