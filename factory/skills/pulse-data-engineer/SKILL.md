---
name: pulse-data-engineer
description: PULSE data pipeline context. Use when working on DevLake, Kafka, sync/metrics workers, DB schema, or data quality.
---
# PULSE Data Engineer Skill
## Architecture: Sources → DevLake (Raw→Tool→Domain) → Sync Worker → Kafka → Metrics Worker → PULSE DB → FastAPI → Frontend.
## Kafka Topics: domain.pr.normalized, domain.issue.normalized, domain.deployment.normalized, domain.sprint.normalized. 2 partitions MVP.
## Tables: eng_pull_requests (generated: lead_time_hours, cycle_time_hours), eng_issues (status_transitions JSONB), eng_deployments, eng_sprints, metrics_snapshots.
## Connector Priority: 1-GitHub, 2-Jira, 3-Pipeline Core, 4-GitLab, 5-Azure DevOps.
## Patterns: Watermark incremental sync, UPSERT on conflict, pre-calculate in metrics_snapshots, manual Kafka commit, metadata validator strips code.
## Performance SLA: DORA query <200ms, CFD <500ms, Scatterplot <500ms, PR list <200ms.
