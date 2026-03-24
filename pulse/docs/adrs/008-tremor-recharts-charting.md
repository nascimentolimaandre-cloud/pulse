# ADR-008: Tremor + Recharts for Dashboard Visualization

**Status:** Accepted
**Date:** 2026-03-24

## Context

PULSE dashboards require two categories of visual components:

1. **Dashboard widgets** -- KPI cards, metric badges, sparklines, trend indicators, status badges. These are structural dashboard elements, not traditional charts.
2. **Data charts** -- Bar charts, line charts, area charts (CFD), scatter plots (Lead Time Distribution), donut charts (Investment Allocation), and stacked bars (Cycle Time Breakdown).

We evaluated Tremor + Recharts, Apache ECharts, and Nivo across six criteria: dashboard-specific components, Tailwind integration, simplicity, bundle size, React nativeness, and chart type coverage.

## Decision

Use Tremor for dashboard widgets and Recharts as the charting foundation:

- **Tremor:** Provides pre-built KPI cards, metric badges, sparklines, progress bars, and other dashboard-specific components. Built on Tailwind CSS and Radix UI. Operates as a copy-paste model (acquired by Vercel in 2024) -- code is copied into the project with full ownership, no runtime dependency.
- **Recharts:** React-native charting library covering bar, line, area, scatter, donut, and composed charts. Declarative API, tree-shakeable, and lightweight.

This combination covers approximately 95% of MVP chart requirements. For advanced visualizations needed in R3+ (heatmaps, treemaps, advanced CFD), Apache ECharts can be added incrementally alongside Recharts without conflict.

## Consequences

**Positive:**
- Tremor provides dashboard-specific components that pure charting libraries lack (KPI cards, badges, status indicators).
- Both libraries are Tailwind-native, ensuring visual consistency with the rest of the UI.
- Copy-paste model means no version lock-in; the code is ours to modify.
- Recharts is lightweight and tree-shakeable, keeping bundle size small.
- Both are React-native, avoiding wrapper-layer issues (unlike echarts-for-react).

**Negative:**
- Recharts lacks some advanced chart types (heatmaps, treemaps, gauge charts) that may be needed in later releases.
- Tremor's copy-paste model means updates from upstream require manual integration.
- Two visualization libraries means two APIs for developers to learn, though they serve distinct purposes.
