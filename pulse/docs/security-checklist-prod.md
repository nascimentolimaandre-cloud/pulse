# PULSE — Security Checklist for Production Deployment

**Status:** PENDING — Apply before first production deploy
**Last updated:** 2026-03-27

---

## 1. DevLake Credentials & Secrets

| Item | Risk | Action | Priority |
|---|---|---|---|
| Jenkins API token stored in DevLake DB | Medium | Move to AWS Secrets Manager; inject at runtime via ECS task definition | P0 |
| GitHub token stored in DevLake DB | Medium | Same as above | P0 |
| `ENCRYPTION_SECRET` is hardcoded default | High | Generate strong 32-char random secret; store in Secrets Manager | P0 |
| `.env` files with plaintext tokens | High | Never deploy `.env` to prod; use Secrets Manager / Parameter Store | P0 |
| `JENKINS_USERNAME` + `JENKINS_API_TOKEN` | Medium | Use a dedicated Jenkins service account with minimal read-only permissions | P0 |

## 2. Network & Access Control

| Item | Risk | Action | Priority |
|---|---|---|---|
| DevLake API exposed on port 8080/4000 | Medium | Run in private subnet; no public ingress. Only Sync Worker and pulse-api access it | P0 |
| DevLake DB exposed on port 5433 | Medium | Private subnet only; security group allows only Sync Worker IP/SG | P0 |
| Jenkins API access | Medium | Allowlist PULSE infra IPs only on Jenkins firewall | P1 |
| No WAF in front of PULSE API | Medium | Add AWS WAF with rate limiting, geo-blocking, common attack rules | P1 |
| No VPC isolation | High | Deploy all services in VPC with private subnets for DB/DevLake, public only for ALB | P0 |

## 3. Container Security

| Item | Risk | Action | Priority |
|---|---|---|---|
| `apache/devlake:latest` unscanned | Medium | Add Trivy scan in CI; pin to specific version tag, not `latest` | P0 |
| Containers running as root | Medium | Add `USER nonroot` to all Dockerfiles; DevLake image needs verification | P1 |
| Read-only filesystem | Low | Set `readOnlyRootFilesystem: true` in ECS task def where possible | P2 |
| No resource limits | Medium | Set CPU/memory limits on all containers to prevent noisy-neighbor | P1 |

## 4. Authentication & Authorization

| Item | Risk | Action | Priority |
|---|---|---|---|
| No auth on PULSE API (MVP) | High | Implement Auth0/Cognito before prod (R1 scope) | P0-R1 |
| No RBAC on dashboard data | Medium | Implement tenant-scoped RLS on all DB queries | P0 |
| DevLake Config UI accessible | Low | Disable DevLake Config UI in prod (no port mapping for 4000) | P1 |
| Jenkins service account permissions | Medium | Ensure read-only: Overall/Read, Job/Read, Run/Read only | P0 |

## 5. Data Security

| Item | Risk | Action | Priority |
|---|---|---|---|
| Metadata-only enforcement | Critical | Verify DevLake NEVER downloads source code — only PR metadata, commit metadata, deploy events | P0 |
| PII in commit authors | Medium | Author names are stored; ensure privacy policy covers this. Consider pseudonymization for non-admin views | P1 |
| Anti-surveillance validation | Critical | All metrics must be team-level only. No individual developer leaderboards or rankings. Audit all API responses | P0 |
| DB encryption at rest | Medium | Enable RDS encryption (AES-256) | P0 |
| TLS for all connections | High | Enforce TLS 1.3 for DB connections (`sslmode=require`), API (HTTPS only), DevLake internal comms | P0 |

## 6. Security Headers & API Hardening

| Item | Risk | Action | Priority |
|---|---|---|---|
| No security headers | Medium | Add Helmet.js middleware: HSTS, CSP, X-Frame-Options, X-Content-Type-Options | P1 |
| No rate limiting on API | Medium | API Gateway throttling: 100 req/s per tenant default | P1 |
| No request size limits | Low | Limit request body to 1MB; reject oversized payloads | P2 |
| CORS misconfigured | Medium | Restrict CORS to PULSE frontend domain only, not `*` | P1 |

## 7. Monitoring & Incident Response

| Item | Risk | Action | Priority |
|---|---|---|---|
| No alerting on DevLake failures | Medium | CloudWatch alarm on ECS task health + sync worker errors | P1 |
| No audit logging | Medium | Log all config changes, connection creates, data access patterns | P1 |
| No incident response plan | Medium | Document runbook for: DevLake down, Jenkins unreachable, data sync stalled | P2 |
| No backup strategy | High | Daily automated backups: PULSE DB (RDS snapshots), DevLake DB | P0 |

## 8. Jenkins-Specific Security

| Item | Risk | Action | Priority |
|---|---|---|---|
| Jenkins token scope | Medium | Use API token (not password); scope to read-only operations | P0 |
| Jenkins API over HTTP | High | Ensure Jenkins base_url uses HTTPS | P0 |
| Credential rotation | Medium | Rotate Jenkins API token every 90 days; automate via Secrets Manager rotation | P2 |
| Build log content | Low | DevLake Jenkins plugin does NOT extract build logs (only metadata). Verify this remains true on plugin updates | P1 |

---

## 9. Operational Safety — READ-ONLY Policy

| Item | Risk | Action | Priority |
|---|---|---|---|
| PULSE agents must NEVER modify external systems | Critical | All Jenkins/Jira/GitHub/DevLake interactions are READ-ONLY. No triggering builds, creating issues, pushing code, or modifying configs on external systems. PULSE is a consumer, not an actor | P0 |
| DevLake plugin configuration | Medium | DevLake plugins only READ from Jenkins/GitHub APIs. Verify no write-back plugins are enabled | P0 |
| Jenkins API token scope | Critical | Token must have ONLY read permissions (Overall/Read, Job/Read, Run/Read). No Build/Execute, Job/Configure, or Admin permissions | P0 |

## Pre-Deploy Gate

Before deploying to production, ALL P0 items must be resolved.
P1 items should be resolved within 2 weeks of prod launch.
P2 items tracked in backlog for R1/R2.

**Reviewer:** pulse-ciso agent
**Sign-off required from:** Engineering Lead + Security
