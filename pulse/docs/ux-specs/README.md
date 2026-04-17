# UX Implementation Specs

This directory holds **implementation specifications** produced by the
`pulse-ux-reviewer` agent after a UX/UI review of a page, journey or component.

## Purpose

Each file is the contract between the designer (`pulse-ux-reviewer`) and the
engineer (`pulse-engineer`). It translates editorial decisions and the hi-fi
prototype into the concrete work items needed to implement the screen in the
production React app (`pulse/packages/pulse-web/`) against the design system.

## Naming

`<page-or-journey-slug>-impl-spec.md`

Examples:
- `pipeline-monitor-impl-spec.md`
- `jira-settings-impl-spec.md`
- `dora-dashboard-impl-spec.md`
- `onboarding-flow-impl-spec.md`

## Contents (mandatory sections)

1. Objective & scope
2. Design rationale
3. Information architecture
4. Component breakdown (existing design-system vs new components)
5. Design tokens used
6. States matrix (loading · empty · healthy · degraded · error · partial)
7. Responsive rules (desktop · tablet · mobile)
8. Accessibility checklist (WCAG AA)
9. Analytics events
10. Open questions / risks

## How to produce

Run `/pulse-ux-review <page-or-journey>` — the reviewer agent writes the spec here.
