# Pipeline Monitor Dashboard -- Component Specification

**Page:** `/integrations/pipeline` (sub-route of Integrations)
**Purpose:** Real-time visualization of the PULSE data ingestion pipeline, showing data flowing from external sources through DevLake collection, normalization, and metric calculation stages.
**Design reference:** Follows existing PULSE design system (globals.css tokens, MetricCard patterns, Sidebar navigation, skeleton loading).

---

## 1. Page Layout

```
+------------------------------------------------------------------+
|  Sidebar  |  TopBar (Team + Period filters)                       |
|           |--------------------------------------------------------|
|           |  Page Header: "Pipeline Monitor"                      |
|           |  Subtitle + Global health badge                       |
|           |--------------------------------------------------------|
|           |  [--- Pipeline Flow Diagram (hero) ------------------] |
|           |                                                        |
|           |  Source --> DevLake --> Sync Worker --> PULSE DB --> Metrics
|           |                                                        |
|           |--------------------------------------------------------|
|           |  Counter Strip (4 MetricCards in a row)                |
|           |--------------------------------------------------------|
|           |  Stage Detail Cards       |  Activity Timeline        |
|           |  (expandable accordion)   |  (scrollable feed)        |
|           |                           |                           |
+------------------------------------------------------------------+
```

### Responsive breakpoints

| Breakpoint | Behavior |
|---|---|
| >= 1280px (xl) | Full layout: flow diagram horizontal, detail cards 2-col + timeline sidebar |
| 1024-1279px (lg) | Flow diagram horizontal, detail cards stack full-width, timeline collapses to bottom |
| 768-1023px (md) | Flow diagram wraps to 2 rows (3+2 nodes), counter strip 2x2 grid |
| < 768px (sm) | Flow diagram vertical stack, counter strip single column, timeline hidden (accessible via tab) |

---

## 2. Component Hierarchy

```
PipelineMonitorPage
  +-- PageHeader
  |     +-- Title ("Pipeline Monitor")
  |     +-- Subtitle
  |     +-- GlobalHealthBadge (status: healthy | degraded | down)
  |
  +-- PipelineFlowDiagram
  |     +-- PipelineNode (x5)
  |     |     +-- NodeIcon (Lucide icon)
  |     |     +-- NodeLabel
  |     |     +-- StatusBadge
  |     |     +-- RecordCount (animated counter)
  |     +-- PipelinePipe (x4, connects adjacent nodes)
  |           +-- AnimatedParticles (CSS animation)
  |           +-- PipeStatusIndicator (color by health)
  |
  +-- CounterStrip
  |     +-- MetricCard ("Total Records")
  |     +-- MetricCard ("Synced Today")
  |     +-- MetricCard ("Pending")
  |     +-- MetricCard ("Errors")
  |
  +-- DetailAndTimelineSection
        +-- StageDetailAccordion
        |     +-- StageCard ("DevLake Collection")
        |     |     +-- BoardProgressRow (per board/project)
        |     +-- StageCard ("Sync Worker")
        |     |     +-- EntitySyncRow (per entity type)
        |     +-- StageCard ("Metrics Worker")
        |           +-- MetricCalcRow (per metric type)
        |
        +-- ActivityTimeline
              +-- TimelineEvent (list, color-coded)
```

---

## 3. Data Types (TypeScript Interfaces)

```typescript
/* ---- Pipeline Health ---- */

type PipelineStageStatus = 'healthy' | 'running' | 'slow' | 'error' | 'idle';

interface PipelineStage {
  id: 'source' | 'devlake' | 'sync_worker' | 'pulse_db' | 'metrics_worker';
  label: string;
  status: PipelineStageStatus;
  /** Icon name from lucide-react */
  icon: string;
  /** Total records processed by this stage (lifetime or current period) */
  recordCount: number;
  /** Timestamp of last successful operation */
  lastActivityAt: string | null;
  /** Human-readable status detail, e.g. "Syncing 3 boards..." */
  statusDetail?: string;
}

interface PipelineConnection {
  from: PipelineStage['id'];
  to: PipelineStage['id'];
  status: 'flowing' | 'slow' | 'blocked' | 'idle';
  /** Records per minute throughput */
  throughputPerMin: number;
}

interface PipelineOverview {
  stages: PipelineStage[];
  connections: PipelineConnection[];
  globalHealth: 'healthy' | 'degraded' | 'down';
}

/* ---- Counter Metrics ---- */

interface PipelineCounters {
  totalRecords: number;
  syncedToday: number;
  pending: number;
  errors: number;
}

/* ---- DevLake Stage Detail ---- */

interface DevLakeBoardStatus {
  boardId: string;
  boardName: string;
  source: 'jira' | 'github' | 'gitlab' | 'azure_devops';
  status: 'collecting' | 'complete' | 'error' | 'queued';
  /** 0-100, percentage of collection complete for current cycle */
  progress: number;
  recordsCollected: number;
  lastCollectedAt: string | null;
  errorMessage?: string;
}

interface DevLakeStageDetail {
  boards: DevLakeBoardStatus[];
  currentCycleStartedAt: string | null;
  collectionFrequencyMin: number;
}

/* ---- Sync Worker Stage Detail ---- */

type EntityType = 'pull_requests' | 'issues' | 'deployments' | 'sprints';

interface EntitySyncStatus {
  entityType: EntityType;
  lastCycleRecords: number;
  lastCycleDurationSec: number;
  lastSyncAt: string | null;
  watermark: string | null;
  status: 'idle' | 'syncing' | 'error';
  errorMessage?: string;
}

interface SyncWorkerStageDetail {
  entities: EntitySyncStatus[];
  syncIntervalMin: number;
  currentCycleStartedAt: string | null;
}

/* ---- Metrics Worker Stage Detail ---- */

type MetricType = 'dora' | 'cycle_time' | 'throughput' | 'lean' | 'sprint';

interface MetricCalcStatus {
  metricType: MetricType;
  lastCalcDurationSec: number;
  lastCalcAt: string | null;
  snapshotsWritten: number;
  status: 'idle' | 'calculating' | 'error';
  errorMessage?: string;
}

interface MetricsWorkerStageDetail {
  metrics: MetricCalcStatus[];
  triggerMode: 'event_driven' | 'scheduled';
}

/* ---- Activity Timeline ---- */

type TimelineEventSeverity = 'success' | 'info' | 'warning' | 'error';

interface TimelineEvent {
  id: string;
  timestamp: string;
  message: string;
  severity: TimelineEventSeverity;
  /** Which stage produced this event */
  stageId: PipelineStage['id'];
  /** Optional structured detail */
  detail?: Record<string, unknown>;
}

/* ---- Full API Response ---- */

interface PipelineMonitorResponse {
  overview: PipelineOverview;
  counters: PipelineCounters;
  devlakeDetail: DevLakeStageDetail;
  syncWorkerDetail: SyncWorkerStageDetail;
  metricsWorkerDetail: MetricsWorkerStageDetail;
  recentEvents: TimelineEvent[];
  /** ISO timestamp of when this snapshot was generated */
  generatedAt: string;
}
```

---

## 4. Component Specifications

### 4.1 PipelineFlowDiagram (Hero Section)

**Layout:** Horizontal flex container with 5 nodes and 4 connecting pipes between them. Centered on the page with generous vertical padding (py-8).

**Dimensions:**
- Container: full width of content area, max-width 960px, centered
- Each node: 120px wide, 140px tall
- Pipes: flex-1 between nodes, 4px tall visual connector

#### PipelineNode

Each node is a vertical card-like element:

```
   +------------------+
   |    [icon]         |    <- 40x40 icon in a colored circle
   |                   |
   |   Stage Name      |    <- text-sm font-semibold
   |   [status badge]  |    <- pill badge, colored by status
   |   12,450 records  |    <- text-xs, animated counter
   +------------------+
```

**Node visual states by status:**

| Status | Icon circle bg | Badge color | Badge text |
|---|---|---|---|
| healthy | `bg-emerald-50` | `bg-emerald-50 text-emerald-700` | "Healthy" |
| running | `bg-blue-50` | `bg-blue-50 text-blue-700` | "Running" |
| slow | `bg-amber-50` | `bg-amber-50 text-amber-700` | "Slow" |
| error | `bg-red-50` | `bg-red-50 text-red-700` | "Error" |
| idle | `bg-surface-tertiary` | `bg-surface-tertiary text-content-tertiary` | "Idle" |

**Node icons (Lucide):**
- Source: `Cable`
- DevLake: `Database`
- Sync Worker: `RefreshCw`
- PULSE DB: `HardDrive`
- Metrics Worker: `Calculator`

**Interaction:** Clicking a node scrolls to its corresponding StageDetailCard. The node has `cursor-pointer`, `hover:shadow-elevated` transition, and a focus ring for keyboard navigation.

#### PipelinePipe

A horizontal connector between two adjacent nodes. The pipe is a 4px-tall rounded bar with animated particles (dots) flowing left to right when active.

**Pipe color by connection status:**

| Status | Pipe bg | Particle color | Animation |
|---|---|---|---|
| flowing | `bg-emerald-100` | `bg-emerald-500` | Active, normal speed (3s) |
| slow | `bg-amber-100` | `bg-amber-500` | Active, slow speed (6s) |
| blocked | `bg-red-100` | `bg-red-500` | Stopped, pulse animation |
| idle | `bg-surface-tertiary` | none | No particles |

**Throughput label:** Centered below the pipe, show `{throughputPerMin} rec/min` in text-xs text-content-tertiary. Hidden when idle (0).

#### CSS Animation: Flowing Particles

The particle effect uses 3 small circles (6px diameter) spaced evenly along the pipe, animated with a translateX keyframe.

```css
/* Pipeline particle flow animation */
@keyframes pipeline-flow {
  0% {
    transform: translateX(-20px);
    opacity: 0;
  }
  10% {
    opacity: 1;
  }
  90% {
    opacity: 1;
  }
  100% {
    transform: translateX(calc(100% + 20px));
    opacity: 0;
  }
}

@keyframes pipeline-flow-slow {
  0% {
    transform: translateX(-20px);
    opacity: 0;
  }
  10% {
    opacity: 1;
  }
  90% {
    opacity: 1;
  }
  100% {
    transform: translateX(calc(100% + 20px));
    opacity: 0;
  }
}

@keyframes pipeline-pulse-blocked {
  0%, 100% {
    opacity: 0.3;
  }
  50% {
    opacity: 1;
  }
}

.pipeline-pipe {
  position: relative;
  height: 4px;
  border-radius: 2px;
  overflow: hidden;
}

.pipeline-particle {
  position: absolute;
  top: -1px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

/* Three particles, staggered start */
.pipeline-pipe--flowing .pipeline-particle:nth-child(1) {
  animation: pipeline-flow 3s linear infinite;
  animation-delay: 0s;
}
.pipeline-pipe--flowing .pipeline-particle:nth-child(2) {
  animation: pipeline-flow 3s linear infinite;
  animation-delay: 1s;
}
.pipeline-pipe--flowing .pipeline-particle:nth-child(3) {
  animation: pipeline-flow 3s linear infinite;
  animation-delay: 2s;
}

/* Slow variant: 6s duration */
.pipeline-pipe--slow .pipeline-particle:nth-child(1) {
  animation: pipeline-flow 6s linear infinite;
  animation-delay: 0s;
}
.pipeline-pipe--slow .pipeline-particle:nth-child(2) {
  animation: pipeline-flow 6s linear infinite;
  animation-delay: 2s;
}
.pipeline-pipe--slow .pipeline-particle:nth-child(3) {
  animation: pipeline-flow 6s linear infinite;
  animation-delay: 4s;
}

/* Blocked: particles stop and pulse in place */
.pipeline-pipe--blocked .pipeline-particle {
  left: 50%;
  animation: pipeline-pulse-blocked 1.5s ease-in-out infinite;
}
```

**Alternative (Tailwind-only):** Use Tailwind `animate-` classes by defining the keyframes in `tailwind.config.ts` under `extend.keyframes` and `extend.animation`. This avoids a separate CSS file and stays consistent with the project approach.

**Reduced motion:** Wrap all animations with `@media (prefers-reduced-motion: reduce)` to disable particle movement. Replace flowing animation with a static gradient or simple opacity indicator.

```css
@media (prefers-reduced-motion: reduce) {
  .pipeline-particle {
    animation: none !important;
    opacity: 0.7;
    left: 50%;
  }
}
```

---

### 4.2 CounterStrip

A row of 4 MetricCards using the existing `MetricCard` component from `@/components/charts/MetricCard.tsx`. These reuse the established pattern but without classification/benchmarks.

**Grid:** `grid grid-cols-1 gap-section-gap sm:grid-cols-2 lg:grid-cols-4`

| Card | Label | Icon hint | Value example | Unit | Trend source |
|---|---|---|---|---|---|
| Total Records | "Total Records" | n/a | 48,231 | "records" | Compare to yesterday |
| Synced Today | "Synced Today" | n/a | 2,415 | "records" | Compare to same weekday last week |
| Pending | "Pending Sync" | n/a | 38 | "records" | Lower is better (isPositive inverted) |
| Errors | "Errors (24h)" | n/a | 3 | "errors" | Lower is better (isPositive inverted) |

**Animated counter:** When the data first loads (and on each refetch), the numeric value should animate from the previous value to the new value over 600ms using a count-up easing (ease-out). Implementation options:
- Framer Motion `useSpring` or `useMotionValue` with `animate`
- Or a lightweight custom hook `useAnimatedNumber(target, duration)` that uses `requestAnimationFrame`

The hook signature:

```typescript
function useAnimatedNumber(
  target: number,
  duration?: number  // default 600ms
): number  // returns the current displayed value, animating toward target
```

---

### 4.3 StageDetailAccordion

Three expandable cards stacked vertically. Each card has a header (always visible) and a collapsible body.

**Container:** `flex flex-col gap-4`

**Card structure (collapsed):**
```
+-------------------------------------------------------------------+
| [icon]  Stage Name      Status Badge      Last run: 2m ago    [v] |
+-------------------------------------------------------------------+
```

**Card structure (expanded):**
```
+-------------------------------------------------------------------+
| [icon]  Stage Name      Status Badge      Last run: 2m ago    [^] |
|-------------------------------------------------------------------|
|  (stage-specific detail rows)                                     |
+-------------------------------------------------------------------+
```

**Expand/collapse:** The chevron toggles (ChevronDown/ChevronUp from Lucide). Use CSS `max-height` transition (300ms ease) or Framer Motion `AnimatePresence` for smooth reveal.

#### 4.3.1 DevLake Collection Card

Header shows aggregate status. Body shows a table/list of boards:

```
| Board               | Source | Status     | Progress        | Records | Last Collected     |
|---------------------|--------|------------|-----------------|---------|---------------------|
| WEB-MOTORS Board    | Jira   | Collecting | [=====>   ] 67% | 1,204   | 5 min ago          |
| webmotors/api       | GitHub | Complete   | [==========] 100| 8,412   | 12 min ago         |
| webmotors/frontend  | GitHub | Error      | [===       ] 30%| 2,100   | Error: timeout     |
```

**Progress bar:** A horizontal bar, 100% width of its cell, 6px tall, rounded-full.
- Track: `bg-surface-tertiary`
- Fill: `bg-emerald-500` (complete), `bg-blue-500` (collecting, with subtle pulse animation), `bg-red-500` (error)
- Text label to the right: `{progress}%` in text-xs

**Error row:** The entire row gets a subtle `bg-red-50` background. The error message appears below the board name in `text-xs text-status-danger`.

#### 4.3.2 Sync Worker Card

Header shows overall sync status and last full cycle duration. Body shows per-entity-type rows:

```
| Entity         | Last Cycle      | Records | Duration | Watermark          | Status  |
|----------------|-----------------|---------|----------|--------------------|---------|
| Pull Requests  | 12 min ago      | 342     | 4.2s     | 2026-04-07T10:30Z  | Idle    |
| Issues         | 12 min ago      | 1,204   | 8.7s     | 2026-04-07T10:30Z  | Idle    |
| Deployments    | 12 min ago      | 56      | 1.1s     | 2026-04-07T10:30Z  | Idle    |
| Sprints        | 12 min ago      | 12      | 0.8s     | 2026-04-07T10:30Z  | Idle    |
```

**Sync interval indicator:** Below the table, a subtle info line: "Sync interval: every {syncIntervalMin} minutes. Next sync in ~{remaining}."

#### 4.3.3 Metrics Worker Card

Header shows aggregate calculation status. Body shows per-metric-type rows:

```
| Metric Type  | Last Calculated | Duration | Snapshots Written | Status      |
|--------------|-----------------|----------|-------------------|-------------|
| DORA         | 8 min ago       | 2.3s     | 4                 | Idle        |
| Cycle Time   | 8 min ago       | 1.8s     | 6                 | Idle        |
| Throughput   | 8 min ago       | 0.9s     | 2                 | Idle        |
| Lean & Flow  | 8 min ago       | 3.1s     | 8                 | Calculating |
| Sprint       | 8 min ago       | 1.2s     | 3                 | Idle        |
```

**"Calculating" status:** Row shows a subtle `animate-pulse` on the status cell, and the status badge uses `bg-blue-50 text-blue-700`.

---

### 4.4 ActivityTimeline

A vertical scrollable feed on the right side of the detail section (at xl breakpoint) or below the accordion (at smaller breakpoints).

**Container:** Fixed height of 480px with `overflow-y-auto`. Sticky header "Recent Activity" with a subtle bottom border.

**Event structure:**
```
  [colored dot]  [relative timestamp]
  Event message text here
  ─────────────────────────────
```

Each event has:
- A 10px colored dot on the left, aligned with the first line
- A thin vertical line connecting dots (timeline rail): `border-l-2 border-border-subtle`
- Timestamp: `text-xs text-content-tertiary`, relative format ("2m ago", "1h ago")
- Message: `text-sm text-content-primary`
- Stage tag: small pill badge `text-[10px]` showing which stage (e.g., "Sync Worker")

**Dot colors by severity:**

| Severity | Dot color | Example message |
|---|---|---|
| success | `bg-emerald-500` | "Sync completed: 241 issues from WEB-MOTORS Board" |
| info | `bg-blue-500` | "Metrics calculation started for DORA" |
| warning | `bg-amber-500` | "Sync slow: GitHub rate limit approaching (4,200/5,000)" |
| error | `bg-red-500` | "Collection failed: ENO board connection timeout" |

**Auto-scroll:** When new events arrive (via polling/refetch), the timeline should scroll to top to show the newest event. Only auto-scroll if the user has NOT manually scrolled down (track scroll position with a ref).

**Empty state:** "No recent pipeline activity" with a `Clock` icon, centered in the container.

---

## 5. State Management and Data Fetching

### TanStack Query Hook

```typescript
function usePipelineMonitor(): UseQueryResult<PipelineMonitorResponse> {
  return useQuery({
    queryKey: ['pipeline-monitor'],
    queryFn: () => apiClient.get<PipelineMonitorResponse>('/api/pipeline/status'),
    refetchInterval: 10_000,     // Poll every 10 seconds for near-real-time
    refetchIntervalInBackground: false,  // Pause when tab is not visible
    staleTime: 5_000,
  });
}
```

### Component State

| Component | Local state | Notes |
|---|---|---|
| PipelineFlowDiagram | None (pure render from query data) | |
| CounterStrip | `previousCounters: PipelineCounters` | Ref to hold previous values for animated transition |
| StageDetailAccordion | `expandedStage: string | null` | Which card is expanded; default: first non-healthy stage, or null if all healthy |
| ActivityTimeline | `userHasScrolled: boolean` | Track whether user has manually scrolled |

### Loading States

On initial page load:
1. Show skeleton versions of all components simultaneously
2. PipelineFlowDiagram skeleton: 5 gray rounded rectangles connected by gray bars, no animation
3. CounterStrip: 4 `MetricCardSkeleton` instances (reuse existing component)
4. StageDetailAccordion: 3 collapsed cards with shimmer on the header text
5. ActivityTimeline: 5 shimmer lines of varying widths

Transition from skeleton to loaded: use `opacity` transition (300ms ease-in) wrapping each section. No staggered reveal -- all sections appear together when data arrives.

### Error State

If the pipeline monitor endpoint fails, show the same centered error pattern used in `integrations.tsx` and `home.tsx`:
- `AlertCircle` icon (48x48, `text-status-danger`)
- "Failed to load pipeline status" heading
- Error message in `text-content-secondary`
- A "Retry" button (`text-brand-primary`, underline on hover) that calls `refetch()`

---

## 6. Accessibility

| Requirement | Implementation |
|---|---|
| Pipeline diagram semantics | Use `role="img"` on the container with `aria-label="Data pipeline flow diagram showing 5 stages"`. Each node is a `button` (since it is clickable) with `aria-label="{stage name}: {status}, {recordCount} records"` |
| Pipe animations | Purely decorative. Mark with `aria-hidden="true"` |
| Reduced motion | All CSS animations gated behind `@media (prefers-reduced-motion: reduce)` -- particles hidden, counters snap instead of animating |
| Accordion | Each StageCard header is a `button` with `aria-expanded="{true|false}"` and `aria-controls="panel-{stageId}"`. The panel has `id="panel-{stageId}"` and `role="region"` |
| Timeline | `role="log"` on the container, `aria-live="polite"` for new events. Each event is an `article` element |
| Keyboard navigation | Tab order: flow nodes left-to-right, then counter cards, then accordion headers, then timeline. Enter/Space to expand accordion, click flow nodes |
| Color contrast | All status text meets 4.5:1 ratio against their backgrounds (verified against globals.css tokens). Never rely on color alone -- status also conveyed via text label |
| Focus rings | Use the default Tailwind `focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:ring-offset-2` pattern matching existing components |

---

## 7. Sidebar Navigation Update

Add a new nav item to the Sidebar between "Integrations" and the collapse button, or nest it as a sub-route of Integrations:

**Option A (flat):** Add to `NAV_ITEMS` array:
```typescript
{ label: 'Pipeline', path: '/integrations/pipeline', icon: Workflow }
```

**Option B (recommended, sub-navigation):** When on the `/integrations` route, show a secondary nav or tab bar at the top of the integrations area with two tabs: "Connections" and "Pipeline Monitor". This avoids sidebar clutter and groups related functionality.

The tab bar follows the existing pattern:
- Container: `flex gap-1 border-b border-border-default mb-6`
- Tab: `px-4 py-2 text-sm font-medium` with active state `border-b-2 border-brand-primary text-brand-primary` and inactive `text-content-secondary hover:text-content-primary`

---

## 8. File Structure (Proposed)

All paths relative to `pulse/packages/pulse-web/src/`:

```
types/
  pipeline.ts                          # All interfaces from section 3

hooks/
  usePipelineMonitor.ts                # TanStack Query hook

components/
  pipeline/
    PipelineFlowDiagram.tsx            # Hero flow visualization
    PipelineNode.tsx                    # Individual stage node
    PipelinePipe.tsx                    # Animated connector between nodes
    CounterStrip.tsx                    # 4 MetricCards row
    StageDetailAccordion.tsx            # Accordion container
    StageCard.tsx                       # Single expandable card
    DevLakeDetail.tsx                   # Board progress rows
    SyncWorkerDetail.tsx               # Entity sync rows
    MetricsWorkerDetail.tsx            # Metric calc rows
    ActivityTimeline.tsx               # Event feed
    TimelineEvent.tsx                  # Single event row
    PipelineMonitorSkeleton.tsx        # Full-page skeleton

routes/
  _dashboard/
    integrations/
      index.tsx                        # Current integrations page (connections)
      pipeline.tsx                     # Pipeline monitor page (new)
```

---

## 9. Animation Performance Notes

- All particle animations use `transform` and `opacity` only (GPU-composited properties). No `left`/`top` animations.
- The counter animation uses `requestAnimationFrame` -- no `setInterval`.
- The 10-second polling interval is conservative. If the API supports WebSocket or SSE in the future, the `refetchInterval` can be removed in favor of push updates. The component structure does not need to change.
- Use `will-change: transform` on `.pipeline-particle` elements to hint browser compositing, but remove it from idle/stopped pipes to free GPU memory.

---

## 10. Sample Mock Data (for Development)

```typescript
const MOCK_PIPELINE_RESPONSE: PipelineMonitorResponse = {
  overview: {
    stages: [
      { id: 'source', label: 'Sources', status: 'healthy', icon: 'Cable', recordCount: 48231, lastActivityAt: '2026-04-07T10:45:00Z' },
      { id: 'devlake', label: 'DevLake', status: 'running', icon: 'Database', recordCount: 47890, lastActivityAt: '2026-04-07T10:44:30Z', statusDetail: 'Collecting 2 boards...' },
      { id: 'sync_worker', label: 'Sync Worker', status: 'healthy', icon: 'RefreshCw', recordCount: 47200, lastActivityAt: '2026-04-07T10:42:00Z' },
      { id: 'pulse_db', label: 'PULSE DB', status: 'healthy', icon: 'HardDrive', recordCount: 47200, lastActivityAt: '2026-04-07T10:42:00Z' },
      { id: 'metrics_worker', label: 'Metrics', status: 'healthy', icon: 'Calculator', recordCount: 23, lastActivityAt: '2026-04-07T10:40:00Z', statusDetail: '23 snapshots' },
    ],
    connections: [
      { from: 'source', to: 'devlake', status: 'flowing', throughputPerMin: 120 },
      { from: 'devlake', to: 'sync_worker', status: 'flowing', throughputPerMin: 85 },
      { from: 'sync_worker', to: 'pulse_db', status: 'flowing', throughputPerMin: 85 },
      { from: 'pulse_db', to: 'metrics_worker', status: 'idle', throughputPerMin: 0 },
    ],
    globalHealth: 'healthy',
  },
  counters: {
    totalRecords: 48231,
    syncedToday: 2415,
    pending: 38,
    errors: 3,
  },
  devlakeDetail: {
    boards: [
      { boardId: 'b1', boardName: 'WEB-MOTORS Board', source: 'jira', status: 'collecting', progress: 67, recordsCollected: 1204, lastCollectedAt: '2026-04-07T10:40:00Z' },
      { boardId: 'b2', boardName: 'webmotors/api', source: 'github', status: 'complete', progress: 100, recordsCollected: 8412, lastCollectedAt: '2026-04-07T10:33:00Z' },
      { boardId: 'b3', boardName: 'webmotors/frontend', source: 'github', status: 'error', progress: 30, recordsCollected: 2100, lastCollectedAt: '2026-04-07T09:15:00Z', errorMessage: 'Connection timeout after 30s' },
    ],
    currentCycleStartedAt: '2026-04-07T10:38:00Z',
    collectionFrequencyMin: 15,
  },
  syncWorkerDetail: {
    entities: [
      { entityType: 'pull_requests', lastCycleRecords: 342, lastCycleDurationSec: 4.2, lastSyncAt: '2026-04-07T10:30:00Z', watermark: '2026-04-07T10:30:00Z', status: 'idle' },
      { entityType: 'issues', lastCycleRecords: 1204, lastCycleDurationSec: 8.7, lastSyncAt: '2026-04-07T10:30:00Z', watermark: '2026-04-07T10:30:00Z', status: 'idle' },
      { entityType: 'deployments', lastCycleRecords: 56, lastCycleDurationSec: 1.1, lastSyncAt: '2026-04-07T10:30:00Z', watermark: '2026-04-07T10:30:00Z', status: 'idle' },
      { entityType: 'sprints', lastCycleRecords: 12, lastCycleDurationSec: 0.8, lastSyncAt: '2026-04-07T10:30:00Z', watermark: '2026-04-07T10:30:00Z', status: 'idle' },
    ],
    syncIntervalMin: 15,
    currentCycleStartedAt: null,
  },
  metricsWorkerDetail: {
    metrics: [
      { metricType: 'dora', lastCalcDurationSec: 2.3, lastCalcAt: '2026-04-07T10:35:00Z', snapshotsWritten: 4, status: 'idle' },
      { metricType: 'cycle_time', lastCalcDurationSec: 1.8, lastCalcAt: '2026-04-07T10:35:00Z', snapshotsWritten: 6, status: 'idle' },
      { metricType: 'throughput', lastCalcDurationSec: 0.9, lastCalcAt: '2026-04-07T10:35:00Z', snapshotsWritten: 2, status: 'idle' },
      { metricType: 'lean', lastCalcDurationSec: 3.1, lastCalcAt: '2026-04-07T10:35:00Z', snapshotsWritten: 8, status: 'calculating' },
      { metricType: 'sprint', lastCalcDurationSec: 1.2, lastCalcAt: '2026-04-07T10:35:00Z', snapshotsWritten: 3, status: 'idle' },
    ],
    triggerMode: 'event_driven',
  },
  recentEvents: [
    { id: 'e1', timestamp: '2026-04-07T10:45:00Z', message: 'Lean metrics recalculation started', severity: 'info', stageId: 'metrics_worker' },
    { id: 'e2', timestamp: '2026-04-07T10:42:00Z', message: 'Sync completed: 1,614 records across 4 entity types', severity: 'success', stageId: 'sync_worker' },
    { id: 'e3', timestamp: '2026-04-07T10:40:00Z', message: 'DevLake collection started for WEB-MOTORS Board', severity: 'info', stageId: 'devlake' },
    { id: 'e4', timestamp: '2026-04-07T10:38:00Z', message: 'Collection failed: webmotors/frontend - Connection timeout', severity: 'error', stageId: 'devlake' },
    { id: 'e5', timestamp: '2026-04-07T10:35:00Z', message: 'DORA metrics calculated: 4 snapshots written', severity: 'success', stageId: 'metrics_worker' },
    { id: 'e6', timestamp: '2026-04-07T10:33:00Z', message: 'GitHub rate limit at 82% (4,100/5,000)', severity: 'warning', stageId: 'source' },
  ],
  generatedAt: '2026-04-07T10:45:12Z',
};
```

---

## 11. Visual Reference (ASCII Wireframe)

### Desktop (xl) -- Full layout

```
 Sources         DevLake          Sync Worker       PULSE DB         Metrics
+----------+   +----------+    +-------------+   +-----------+   +----------+
|  [Cable]  |   | [Database]|   | [RefreshCw] |   | [HardDrive]|  |[Calcultr]|
|           |   |           |   |             |   |            |  |          |
| Sources   |   | DevLake   |   | Sync Worker |   | PULSE DB   |  | Metrics  |
| [Healthy] |-->| [Running] |--->| [Healthy]   |--->| [Healthy]  |->| [Healthy]|
| 48,231    |   | 47,890    |   | 47,200      |   | 47,200     |  | 23 snaps |
+----------+   +----------+    +-------------+   +-----------+   +----------+
     |||  flowing 120/min  |||  flowing 85/min  |||  flowing 85/min |||  idle

+-------------+ +-------------+ +-------------+ +-------------+
| Total Recs  | | Synced Today| | Pending     | | Errors (24h)|
| 48,231      | | 2,415       | | 38          | | 3           |
| +12% vs yst | | +5% vs wk   | | -24% (good) | | +1 (bad)    |
+-------------+ +-------------+ +-------------+ +-------------+

+-----------------------------------------+  +------------------------+
| v DevLake Collection        [Running]   |  | Recent Activity        |
|-----------------------------------------|  |------------------------|
| WEB-MOTORS   Jira  [=====>    ] 67%     |  | * Lean metrics started |
| webmotors/api GH   [==========] 100%   |  | * Sync completed: 1614 |
| webmotors/fe  GH   [===       ] 30% ERR|  | * Collection started   |
+-----------------------------------------+  | ! Collection failed    |
| > Sync Worker                [Healthy]  |  | * DORA calculated      |
+-----------------------------------------+  | ~ Rate limit at 82%   |
| > Metrics Worker             [Healthy]  |  +------------------------+
+-----------------------------------------+
```

---

## 12. Open Questions for Product Review

1. **Polling vs push:** The spec assumes 10-second polling. If the backend can support SSE (Server-Sent Events) on this endpoint, the real-time experience improves significantly with less server load. Should this be a fast-follow?

2. **Historical view:** This spec covers current/live status only. A "Pipeline History" tab showing success/failure over time (e.g., a timeline chart of sync durations over the last 24h) would be valuable but is out of scope for v1.

3. **Manual trigger:** Should there be a "Trigger Sync Now" button? This would violate the READ-ONLY principle for the frontend and require careful RBAC. Recommend deferring to a future release with admin role gating.

4. **Alert configuration:** The pipeline monitor shows current status but does not configure alerting thresholds (e.g., "alert if sync fails 3 times in a row"). This belongs in a separate Settings page.
