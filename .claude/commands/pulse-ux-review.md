---
description: Review or redesign the UX/UI of a PULSE page, journey, component or state. Delegates to pulse-ux-reviewer for editorial concepts + implementation spec + FDD backlog.
argument-hint: <page-or-journey> (e.g., "Pipeline Monitor", "DORA dashboard", "Jira Settings", "Onboarding flow", "Home")
---

# UX/UI Review: **$ARGUMENTS**

Delegate to **`pulse-ux-reviewer`** to produce a principal-level UX/UI review of
`$ARGUMENTS` with the three mandatory deliverables.

## Inputs the agent must confirm (or explicitly assume)

1. **Page / journey in scope** — from `$ARGUMENTS`; locate current prototype under
   `pulse/pulse-ui/` and/or production route under `pulse/packages/pulse-web/src/routes/`
2. **Primary persona** — Carlos (EM) / Ana (CTO) / Marina (Sr Dev) / Priya (Agile
   Coach) / Roberto (CFO) / Lucas (Data Platform)
3. **Top job-to-be-done** — the single decision the page must unlock
4. **Release tag** — MVP / R1 / R2 / R3 / R4
5. **Critical states** — which of loading / empty / healthy / degraded / error / partial
   matter most for this page
6. **Data contract** — endpoints, fields, cadence; default to what is shipped in the
   production API unless the spec says otherwise
7. **Scale** — assume Webmotors worst case (283 repos, 69 Jira projects, 577 Jenkins
   jobs, 373k issues, 63k PRs) unless told otherwise
8. **Anti-surveillance boundary** — confirm author-level data is off-limits

If any input is missing, state the assumption in the deliverable and proceed.

## Expected output (always, in this order)

### A. Three editorial concepts
Each concept comes with:
- Hi-fi screenshot (desktop ≥1280px)
- Hi-fi screenshot of **one** critical alternative state (empty / degraded / incident)
- Drawer or detail view if the concept relies on drill-down
- One responsive view (mobile OR tablet)
- Editorial thesis (3–5 lines)
- Two known limitations

### B. Final recommendation
- Which concept wins and why
- **Three** pre-dev adjustments to the winning concept, each with a short justification

### C. Three mandatory deliverables
1. **Updated frontend code (HTML + CSS + JS)** saved under
   `pulse/pulse-ui/<page-path>/` — runnable, uses tokens.css, BEM, ES modules, WCAG AA,
   all states, responsive
2. **Implementation spec** at `pulse/docs/ux-specs/<page-slug>-impl-spec.md` — the
   contract handed to `pulse-engineer` for componentisation against the design system
3. **FDD backlog** at `pulse/docs/backlog/<page-slug>-backlog.md` — feature cards with
   BDD criteria, persona, release, priority, dependencies, estimate, analytics events

## Constraints the agent must respect

- PULSE is **READ-ONLY** against external systems — never design CTAs that trigger
  external builds/syncs
- **Anti-surveillance** is non-negotiable — no individual-author data in perf/delay
  contexts
- **Real scale** — never design for 3-item lists that collapse at customer scale
- **WCAG AA floor** — status is always colour + icon + label
- **Copy in PT-BR** — direct, professional, no emoji
- **Tokens only** — no hardcoded hex values outside `tokens.css`

## Self-review checklist (agent must confirm all ticks before returning)

- [ ] 3 concepts × (screenshot + alt-state + drawer + responsive + thesis + 2 limitations)
- [ ] Final recommendation + exactly 3 pre-dev adjustments
- [ ] All 6 states (loading / empty / healthy / degraded / error / partial) addressed
- [ ] Responsive spec for desktop / tablet / mobile
- [ ] Real-scale validation — layout survives worst-case customer numbers
- [ ] Anti-surveillance — no individual author in any perf/health context
- [ ] WCAG AA — contrast, labels, focus order, reduced-motion
- [ ] PULSE tokens only — no hardcoded hex
- [ ] PT-BR copy, professional tone
- [ ] Deliverable 1 (code) path returned to user
- [ ] Deliverable 2 (impl spec) path returned to user
- [ ] Deliverable 3 (FDD backlog) path returned to user

## Hand-off

Once the review is complete, the user will typically route:
- The **impl spec** to `pulse-engineer` for React + design system implementation
- The **FDD backlog** to `pulse-product-director` for release planning and
  prioritisation against MVP / R1–R4 roadmap
- The **prototype code** stays in `pulse/pulse-ui/` as the reference for visual QA
