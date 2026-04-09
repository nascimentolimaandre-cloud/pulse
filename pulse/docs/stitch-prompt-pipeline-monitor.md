# Stitch Prompt: Pipeline Monitor Dashboard

> Copy everything below the line into Google Stitch to generate the Pipeline Monitor screen.

---

## Context

You are designing a **Pipeline Monitor Dashboard** for **PULSE**, an Engineering Intelligence SaaS platform. This page gives engineering managers real-time visibility into a 5-stage data ingestion pipeline: **Sources -> DevLake -> Sync Worker -> PULSE DB -> Metrics Worker**. The goal is to answer "Is my data flowing?" in under 2 seconds.

This page lives inside an existing dashboard application with a fixed left sidebar (240px, dark indigo-900 background) and a top filter bar (56px). The Pipeline Monitor is accessed as a tab within the `/integrations` page, alongside the existing "Connections" tab.

## Design System

### Brand & Colors
- **Brand primary:** Indigo-500 (`#6366F1`), hover Indigo-600 (`#4F46E5`)
- **Background:** White (`#FFFFFF`) primary, Gray-50 (`#F9FAFB`) secondary, Gray-100 (`#F3F4F6`) tertiary
- **Text:** Gray-900 (`#111827`) primary, Gray-500 (`#6B7280`) secondary, Gray-400 (`#9CA3AF`) tertiary
- **Borders:** Gray-200 (`#E5E7EB`) default, Gray-100 (`#F3F4F6`) subtle
- **Status colors:** Emerald-500 (`#10B981`) success/healthy, Blue-500 (`#3B82F6`) info/running, Amber-500 (`#F59E0B`) warning/stale, Red-500 (`#EF4444`) danger/error, Gray-300 idle
- **Card shadow:** `0 1px 3px rgba(0,0,0,0.05)`, elevated: `0 4px 12px rgba(0,0,0,0.08)`
- **Card radius:** 12px, button radius: 8px, badge radius: full/pill

### Typography
- **Font:** Inter (all weights)
- **Page title (H1):** Inter 600, 24px
- **Section title (H2):** Inter 600, 18px
- **Card title (H3):** Inter 500, 14px
- **Body:** Inter 400, 14px
- **Metric value (KPI):** Inter 700, 28px
- **Small label:** Inter 400, 12px
- **Monospace (data):** JetBrains Mono 400, 13px

### Component Library
- shadcn/ui components (Radix primitives + Tailwind)
- Lucide React icons
- Cards with white background, 1px gray-200 border, 12px radius, subtle shadow
- Status badges as pills: colored background (50 shade) + colored text (700 shade)

### Layout Patterns
- Sidebar: fixed 240px, dark (`#312E81` indigo-900)
- Content area: fluid, padded 24px
- Section gap: 24px
- Card padding: 20px
- Skeleton loading (shimmer), never spinners

## Screen: Pipeline Monitor

### Page Header
- Tab bar at top of content area with two tabs: "Connections" (existing) and "Pipeline" (active, with indigo-500 bottom border)
- Page title: "Pipeline Monitor" (H1, 24px, semi-bold)
- Subtitle: "Real-time data ingestion status" (14px, gray-500)
- Global health badge next to subtitle: a pill showing overall status (e.g., green pill "Healthy", or red pill "Error")
- Freshness indicator: right-aligned small text "Updated 5s ago" with a subtle refresh icon, auto-incrementing

### Hero Section: Pipeline Flow Diagram
A horizontal row of 5 stage nodes connected by animated pipes, centered on the page (max-width 960px).

**Each node** is a vertical card (120px wide, ~140px tall) containing:
1. A 40x40 circle with a Lucide icon (colored by status)
2. Stage name (14px, semi-bold)
3. Status badge pill (e.g., green "Healthy", blue pulsing "Running", yellow "Stale", red "Error", gray "Idle")
4. Key metric (12px, monospace): record count or "Task 3/5" progress

**Nodes (left to right):**
| Node | Icon | Example metric |
|------|------|----------------|
| Sources | Cable | "3 active, 0 errors" |
| DevLake | Database | "Running - Task 3/5" or "Complete" |
| Sync Worker | RefreshCw | "47,200 records" |
| PULSE DB | HardDrive | "47,200 records" |
| Metrics | Calculator | "23 snapshots" |

**Pipes** between nodes: 4px tall rounded bars connecting adjacent nodes. When data is flowing, show 3 small dots (6px circles) animating left-to-right along the pipe (CSS translateX keyframe, 3s duration, staggered by 1s each). Pipe colors:
- Flowing: emerald-100 bar, emerald-500 dots
- Slow: amber-100 bar, amber-500 dots (6s animation)
- Blocked: red-100 bar, red-500 dots pulsing in place
- Idle: gray-100 bar, no dots

Below each pipe: throughput label "120 rec/min" in 12px gray-400 text.

**Responsive:** At <768px, nodes stack vertically with vertical pipes.

### Counter Strip
A row of 4 metric cards below the flow diagram, using the standard MetricCard pattern:

| Card | Value | Trend |
|------|-------|-------|
| Total Records | 48,231 | +12% vs yesterday |
| Synced Today | 2,415 | +5% vs same day last week |
| Pending Sync | 38 | -24% (lower is better, show green arrow) |
| Errors (24h) | 3 | +1 (higher is bad, show red arrow) |

Grid: 4 columns on desktop, 2x2 on tablet, 1 column on mobile.
Numbers should animate (count up) when data loads, 600ms ease-out.

### Detail Section (Two columns on desktop)

**Left column (60%): Stage Detail Accordion**
Three collapsible cards stacked vertically:

1. **DevLake Collection** - Header: Database icon + "DevLake Collection" + status badge + "Last run: 5m ago" + chevron
   - Expanded body: Table with columns: Board Name | Source (Jira/GitHub icon) | Status | Progress Bar | Records | Last Collected
   - Progress bar: 6px tall, rounded, colored by status (blue=collecting, green=complete, red=error)
   - Error rows: subtle red-50 background with error message below board name in 12px red-500 text
   - Example rows:
     - "WEB-MOTORS Board" | Jira | Collecting | [=====> ] 67% | 1,204 | 5m ago
     - "webmotors/api" | GitHub | Complete | [==========] 100% | 8,412 | 12m ago
     - "webmotors/frontend" | GitHub | Error | [=== ] 30% | 2,100 | Error: timeout

2. **Sync Worker** - Header: RefreshCw icon + "Sync Worker" + status badge + chevron
   - Expanded body: Table with columns: Entity | Last Cycle | Records | Duration | Watermark | Status
   - Example rows: Pull Requests | 12m ago | 342 | 4.2s | 2026-04-07T10:30Z | Idle
   - Footer line: "Sync interval: every 15 minutes. Next sync in ~3 min."

3. **Metrics Worker** - Header: Calculator icon + "Metrics Worker" + status badge + chevron
   - Expanded body: Table with columns: Metric Type | Last Calculated | Duration | Snapshots Written | Status
   - "Calculating" status rows show subtle blue pulse animation
   - Example rows: DORA | 8m ago | 2.3s | 4 | Idle

**Right column (40%): Activity Timeline**
A vertical scrollable feed (480px fixed height) with:
- Sticky header "Recent Activity" with subtle bottom border
- Each event: colored dot (10px) on left + vertical timeline rail (2px gray-100 line) + relative timestamp (12px, gray-400) + message (14px) + stage pill badge (10px text)
- Dot colors: emerald=success, blue=info, amber=warning, red=error
- Example events:
  - (blue dot) "Lean metrics recalculation started" | Metrics Worker | 2m ago
  - (green dot) "Sync completed: 1,614 records across 4 entity types" | Sync Worker | 5m ago
  - (red dot) "Collection failed: webmotors/frontend - Connection timeout" | DevLake | 7m ago
  - (amber dot) "GitHub rate limit at 82% (4,100/5,000)" | Sources | 12m ago

### Record Counts Table (Optional section, below detail)
A summary comparison table:

| Entity | DevLake | PULSE DB | Last Synced | Kafka Lag |
|--------|---------|----------|-------------|-----------|
| Pull Requests | 1,247 | 1,243 | 2 min ago | 4 |
| Issues | 3,891 | 3,891 | 2 min ago | 0 |

Mismatched rows (DevLake count != PULSE DB count) highlighted with amber-50 background and tooltip "4 records pending sync".

### Error Panel (Collapsible)
Below the record counts table:
- Header: "Errors (3)" with red badge, or "No recent errors" with green check icon
- Expanded when errors exist, collapsed when none
- Each error: warning icon + stage name + entity + relative timestamp + truncated message (200 chars max)

### Loading State
When data is loading, show:
- Flow diagram: 5 gray rounded rectangles connected by gray bars (no animation)
- Counter strip: 4 shimmer skeleton cards
- Accordion: 3 collapsed cards with shimmer text in headers
- Timeline: 5 shimmer lines of varying widths

All sections transition from skeleton to loaded simultaneously with 300ms opacity ease-in.

### Empty/Error State
If the API fails:
- Centered AlertCircle icon (48x48, red-500)
- "Failed to load pipeline status" heading
- Error message in gray-500
- "Retry" text button in indigo-500

## Visual Mood

Think GitLab CI/CD pipeline visualization meets Datadog infrastructure monitoring, but cleaner and more minimal. The animated flowing dots in the pipes are the signature visual element -- they give the dashboard a living, breathing quality that immediately communicates "data is moving through the system." The overall aesthetic is professional, calm, and information-dense without being cluttered.

## Accessibility Requirements
- All status communicated via both color AND text labels
- Pipeline diagram nodes are keyboard-navigable buttons
- Accordion panels use proper aria-expanded/aria-controls
- Timeline uses role="log" with aria-live="polite"
- Particle animations respect prefers-reduced-motion (replaced with static indicators)
- All text meets WCAG AA contrast ratios (4.5:1 minimum)

## Data for Prototype
Use this mock data to populate the screen:
- 3 active source connections (2 GitHub, 1 Jira)
- DevLake: "Running" status, collecting board "WEB-MOTORS Board" at 67% progress
- Sync Worker: "Healthy", last sync 12 minutes ago, 47,200 total records
- PULSE DB: 47,200 records (in sync)
- Metrics Worker: "Healthy", 23 snapshots, "Lean & Flow" currently calculating
- 6 timeline events (mix of success, info, warning, error)
- 3 errors in the error panel
- Counter values: Total 48,231 | Synced Today 2,415 | Pending 38 | Errors 3
