export interface MetricTrend {
  direction: 'up' | 'down' | 'flat';
  percentage: number;
  isPositive: boolean;
  /** false when no previous period data exists for comparison */
  hasHistoricalData?: boolean;
}

export interface MetricTarget {
  value: number;
  met: boolean;
}

export type DoraClassification = 'elite' | 'high' | 'medium' | 'low';

export interface BenchmarkThresholds {
  elite: string;
  high: string;
  medium: string;
  low: string;
}

export interface DoraMetricItem {
  label: string;
  value: number;
  unit: string;
  trend: MetricTrend;
  classification: DoraClassification;
  sparklineData: number[];
  target?: MetricTarget;
  benchmarks?: BenchmarkThresholds;
}

/**
 * Variant of DoraMetricItem for the Home dashboard where the backend may return
 * `null` for metrics that require future pipeline work (e.g. MTTR, which depends
 * on the incident ingestion scheduled for R1).
 */
export interface HomeMetricItem {
  label: string;
  /** `null` when backend has no data yet — UI must render "—" with tooltip. */
  value: number | null;
  unit: string;
  trend: MetricTrend;
  /** `null` when a classification cannot be derived. */
  classification: DoraClassification | null;
  sparklineData: number[];
  benchmarks?: BenchmarkThresholds;
  /** MTTR-only (FDD-DSH-050). Resolved incidents that contributed to the median. */
  incidentCount?: number | null;
  /** MTTR-only (FDD-DSH-050). Failures still open (no recovery in window). */
  openIncidentCount?: number | null;
}

export interface DoraMetrics {
  deploymentFrequency: DoraMetricItem;
  leadTimeForChanges: DoraMetricItem;
  changeFailureRate: DoraMetricItem;
  meanTimeToRestore: DoraMetricItem;
  overallClassification: DoraClassification;
  period: string;
  teamId: string;
}

export interface CycleTimePhase {
  name: string;
  medianHours: number;
  color: string;
  isBottleneck: boolean;
}

export interface CycleTimeBreakdown {
  totalMedianHours: number;
  phases: CycleTimePhase[];
  trend: MetricTrend;
  sparklineData: number[];
  period: string;
  teamId: string;
}

export interface ThroughputDataPoint {
  week: string;
  merged: number;
  opened: number;
}

export interface ThroughputData {
  weeklyData: ThroughputDataPoint[];
  averageMergedPerWeek: number;
  trend: MetricTrend;
  sparklineData: number[];
  period: string;
  teamId: string;
}

export interface LeanMetrics {
  wipCount: number;
  wipLimit: number;
  wipAgingItems: number;
  leadTimeP50Days: number;
  leadTimeP85Days: number;
  leadTimeP95Days: number;
  cfdData: CfdDataPoint[];
  scatterplotData: ScatterplotDataPoint[];
  period: string;
  teamId: string;
}

export interface CfdDataPoint {
  week: string;
  backlog: number;
  todo: number;
  inProgress: number;
  review: number;
  done: number;
}

export interface ScatterplotDataPoint {
  id: string;
  title: string;
  leadTimeDays: number;
  closedAt: string;
  isOutlier: boolean;
}

export interface SprintMetrics {
  committed: number;
  added: number;
  completed: number;
  removed: number;
  carryOver: number;
  completionRate: number;
}

export interface SprintOverview {
  id: string;
  name: string;
  startDate: string;
  endDate: string;
  status: 'active' | 'completed' | 'planned';
  metrics: SprintMetrics;
  burndownData: BurndownDataPoint[];
  teamId: string;
}

export interface BurndownDataPoint {
  day: string;
  ideal: number;
  actual: number;
}

export interface PullRequest {
  id: string;
  title: string;
  author: string;
  avatarUrl: string;
  repository: string;
  createdAt: string;
  ageDays: number;
  size: 'XS' | 'S' | 'M' | 'L' | 'XL';
  linesAdded: number;
  linesDeleted: number;
  reviewers: string[];
  status: 'open' | 'draft' | 'review_requested';
  url: string;
}

/* ── Home Dashboard ── */

export interface LeadTimeCoverage {
  /** PRs in the period with a real `deployed_at` timestamp linked. */
  covered: number;
  /** Total PRs merged in the period (denominator). */
  total: number;
  /** covered / total — ratio between 0 and 1. */
  pct: number;
}

export interface HomeMetrics {
  deploymentFrequency: DoraMetricItem;
  /** LEGACY inclusive variant — uses merged_at fallback. Kept for back-compat. */
  leadTimeForChanges: DoraMetricItem;
  /** Strict DORA Lead Time — only PRs with deployed_at. May be null when sample <5. */
  leadTimeStrict: HomeMetricItem;
  /** Coverage data for the strict card (covered / total / pct). */
  leadTimeCoverage: LeadTimeCoverage | null;
  changeFailureRate: DoraMetricItem;
  /** MTTR/Time to Restore — backend returns null until incident ingestion ships (R1, FDD-DSH-050). */
  timeToRestore: HomeMetricItem;
  cycleTime: DoraMetricItem;
  /** Cycle Time P85 — tail latency, from /metrics/cycle-time breakdown.total_p85. */
  cycleTimeP85: HomeMetricItem;
  wipCount: DoraMetricItem;
  throughput: DoraMetricItem;
  period: string;
  teamId: string;
}

/* ── Throughput Extended ── */

export interface ThroughputAnalytics {
  avgPrSize: number;
  avgFirstReviewTimeHours: number;
  avgReviewTurnaroundHours: number;
  prSizeDistribution: PrSizeDistributionItem[];
}

export interface PrSizeDistributionItem {
  size: 'XS' | 'S' | 'M' | 'L' | 'XL';
  count: number;
}

export interface ThroughputResponse {
  weeklyData: ThroughputDataPoint[];
  averageMergedPerWeek: number;
  trend: MetricTrend;
  sparklineData: number[];
  analytics: ThroughputAnalytics;
  period: string;
  teamId: string;
}

/* ── Sprint Extended ── */

export interface SprintComparisonItem {
  sprintName: string;
  committed: number;
  completed: number;
}

export interface SprintResponse {
  current: SprintOverview | null;
  recent: SprintOverview[];
  comparison: SprintComparisonItem[];
  velocityTrend: 'improving' | 'stable' | 'declining';
}

/* ── Integration ── */

export interface Integration {
  id: string;
  name: string;
  type: 'github' | 'gitlab' | 'jira' | 'azure_devops';
  status: 'active' | 'syncing' | 'error' | 'inactive';
  lastSyncAt: string | null;
  reposMonitored: number;
  errorMessage?: string;
}
