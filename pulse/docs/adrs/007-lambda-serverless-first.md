# ADR-007: AWS Lambda Serverless-First with One ECS Fargate Exception

**Status:** Accepted
**Date:** 2026-03-24

## Context

PULSE needs compute for five workloads: two API servers (NestJS, FastAPI), a sync worker (cron), a metrics worker (event-driven), and a notification worker (event-driven). The classic approach is ECS Fargate containers running 24/7, but at MVP scale most of these workloads are idle the vast majority of the time.

An earlier architecture revision used ECS Fargate for all services at an estimated $250-280/month. Lambda pricing is per-invocation, meaning idle time costs nothing.

The sole exception is Apache DevLake, a stateful Go application with an internal scheduler that must run continuously. It cannot be adapted to Lambda's request/response model.

## Decision

Run all PULSE compute on AWS Lambda except DevLake:

| Workload | Compute | Trigger |
|---|---|---|
| pulse-api (NestJS) | Lambda (512MB-1GB) | API Gateway |
| pulse-data (FastAPI) | Lambda (512MB-1GB) | API Gateway |
| Sync Worker | Lambda (1-2GB) | EventBridge cron (every 15 min) |
| Metrics Worker | Lambda (1-2GB) | MSK Event Source Mapping |
| Notification Worker | Lambda | MSK Event Source Mapping |
| DevLake | ECS Fargate (1 task, 1 vCPU, 2GB) | Always-on |

Cold start mitigation: Provisioned Concurrency (1-2 instances) for the pulse-api Lambda at approximately $5-10/month. FastAPI cold start of 1-2 seconds is acceptable for analytics queries. Workers have no cold-start sensitivity since they process asynchronously.

## Consequences

**Positive:**
- Estimated cost of $120-180/month, saving 30-40% compared to full ECS.
- Automatic scaling from zero to 1000 concurrent executions with no capacity planning.
- Zero server management: no OS patches, no container orchestration, no auto-scaling policies.
- Pay-per-request model aligns cost with actual usage during early growth.

**Negative:**
- Cold starts add 1-2 seconds latency on first request after idle periods (mitigated by Provisioned Concurrency for the main API).
- Lambda's 15-minute execution limit constrains long-running sync operations (mitigated by designing sync as incremental batches).
- VPC-attached Lambdas require NAT Gateway for outbound internet access, adding approximately $30/month.
- Debugging distributed Lambda invocations requires X-Ray tracing setup.
