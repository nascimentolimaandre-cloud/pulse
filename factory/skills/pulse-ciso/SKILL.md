---
name: pulse-ciso
description: PULSE security context. Use when reviewing security, IAM, encryption, compliance, or container hardening.
---
# PULSE CISO Skill
## Core Principle: Metadata-only. NEVER source code, diffs, or file contents. Enforce at ingestion boundary.
## MVP Security: .env in .gitignore, PostgreSQL ssl=require, HTTPS, Trivy+npm audit+pip audit in CI, RLS, non-root Docker, gitleaks pre-commit, Helmet.js, rate limiting.
## R1: OAuth 2.0/OIDC, JWT (15min/7d), SSO/SAML, RBAC, audit logging.
## R2-3: WAF, Shield, Secrets Manager rotation, VPC hardening, GuardDuty, Security Hub, CloudTrail.
## R4: SOC 2 Type II, GDPR, LGPD, pentest.
## IAM: One role per Lambda function. Least privilege. VPC: Public (ALB) → Private (Lambda/ECS) → Data (RDS/MSK).
