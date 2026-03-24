# ADR-012: S3 + CloudFront for SPA Hosting

**Status:** Accepted
**Date:** 2026-03-24

## Context

The PULSE frontend is a static Single-Page Application (React + Vite) that compiles to HTML, JavaScript, and CSS files. It needs to be served globally with low latency, support client-side routing (deep links), and handle cache invalidation on deployments.

Options considered: S3 + CloudFront, Vercel, Netlify, and ECS/Nginx container. A container serving static files wastes compute resources. Vercel and Netlify add vendor lock-in and cost more at scale. S3 + CloudFront is the standard AWS-native solution for static hosting.

## Decision

Host the SPA on S3 with CloudFront as the CDN:

- **S3 bucket:** Private bucket (no public access). Stores the `dist/` output from `vite build`. Versioned for rollback capability.
- **CloudFront distribution:** Serves static assets from edge locations globally. Configured with an Origin Access Identity (OAI) to access the private S3 bucket.
- **Client-side routing:** CloudFront custom error response returns `index.html` with HTTP 200 for all 404s, enabling TanStack Router to handle deep links.
- **Cache strategy:** Hashed asset filenames (e.g., `main.a1b2c3.js`) get long cache TTLs (1 year). `index.html` gets short TTL (5 minutes) or CloudFront invalidation on deploy.
- **Deployment:** CI pipeline runs `vite build`, uploads to S3 via `aws s3 sync`, and creates a CloudFront invalidation for `index.html`.

## Consequences

**Positive:**
- Cost: approximately $1-5/month for a low-traffic SPA (S3 storage + CloudFront requests).
- Global edge delivery with sub-100ms latency for static assets.
- Zero server management: no containers, no scaling configuration, no OS patches.
- Simple deployment pipeline: upload files, invalidate cache, done.

**Negative:**
- No server-side logic at the edge (acceptable since the SPA handles all rendering client-side).
- CloudFront invalidation can take 1-2 minutes to propagate globally after deployment.
- Debugging CloudFront caching issues (stale assets, incorrect headers) can be frustrating.
- ACM certificate must be provisioned in us-east-1 for CloudFront, regardless of the primary region.
