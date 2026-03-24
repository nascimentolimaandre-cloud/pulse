# ADR-006: React 19 + Vite 6 as Single-Page Application

**Status:** Accepted
**Date:** 2026-03-24

## Context

PULSE is a dashboard SaaS product -- 100% authenticated, no SEO requirements, heavy data visualization with interactive charts, global filters, drill-downs, and real-time updates. Five frontend frameworks were evaluated: React + Vite, Next.js, Vue + Nuxt, SvelteKit, and Angular.

Next.js scored well overall but its SSR/SSG capabilities are irrelevant (and even harmful due to hydration mismatches with dynamic chart data) for an authenticated dashboard application. The App Router adds complexity (Server Components, cache policies, client/server boundaries) without benefit for our use case.

## Decision

Build the frontend as a React 19 + Vite 6 Single-Page Application with TypeScript 5.x strict mode. The full stack:

- **Routing:** TanStack Router (type-safe, file-based conventions)
- **Server state:** TanStack Query (caching, background refetch, optimistic updates)
- **Client state:** Zustand (lightweight, no boilerplate)
- **UI components:** shadcn/ui (Radix primitives + Tailwind, copy-paste ownership)
- **Charts:** Tremor (dashboard widgets) + Recharts (custom charts)
- **Tables:** TanStack Table v8 (sorting, filtering, pagination)
- **CSS:** Tailwind CSS 4
- **Testing:** Vitest (unit) + Testing Library (component) + Playwright (E2E)

The SPA builds to a static `dist/` folder deployed to S3 + CloudFront.

## Consequences

**Positive:**
- Zero SSR overhead: no hydration mismatches, no server/client component boundaries.
- Vite provides sub-second hot module replacement in development.
- React has the largest charting ecosystem (Recharts, Tremor, Nivo, ECharts wrappers).
- Static output means trivial deployment (S3 upload + CloudFront invalidation).
- Largest hiring pool: React + TypeScript is the industry standard.

**Negative:**
- No server-side rendering means the initial HTML is an empty shell until JavaScript loads (acceptable since there is no SEO need and users are authenticated).
- Client-side routing requires CloudFront to rewrite 404s to index.html for deep links to work.
- Bundle size must be managed carefully as the dashboard grows (mitigated by Vite's automatic code splitting).
