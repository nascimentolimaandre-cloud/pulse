# ADR-004: MSK Serverless (Kafka) as Event Backbone

**Status:** Accepted
**Date:** 2026-03-24

## Context

PULSE's data pipeline has three stages: ingestion (DevLake sync), metric calculation, and notification. These stages have different throughput characteristics and failure modes. Tight coupling between them would mean a failure in metric calculation blocks notifications, or a slow sync stalls the entire pipeline.

We need an event backbone that decouples producers from consumers, supports replay on failure, and scales with event volume without manual tuning.

## Decision

Use AWS MSK Serverless (Apache Kafka managed) as the event backbone. Kafka topics follow the pattern `domain.<entity>.<event>` (e.g., `domain.pr.normalized`, `metrics.dora.calculated`).

Lambda functions consume events via MSK Event Source Mapping with configurable batch size (100 events) and batching window (30 seconds). This means Lambda scales automatically with Kafka partition throughput -- zero consumer group management.

For local development, Kafka runs in Docker via Confluent's KRaft image (no ZooKeeper dependency).

## Consequences

**Positive:**
- Pipeline stages are fully decoupled; each can fail, retry, and scale independently.
- Event replay enables reprocessing historical data when metric formulas change.
- MSK Serverless requires zero cluster management (no broker sizing, partition rebalancing, or ZooKeeper).
- Lambda Event Source Mapping provides automatic scaling, dead-letter queues, and retry policies.

**Negative:**
- MSK Serverless costs approximately $30-50/month even at low throughput, making it the most expensive infrastructure component in the MVP.
- Kafka adds operational complexity for debugging (topic offsets, consumer lag, serialization issues).
- Local development requires a Kafka container, increasing the Docker Compose footprint.
- Event ordering guarantees require careful partition key design (by organization_id).
