// ---------------------------------------------------------------------------
// BC4 Metrics — Shared type definitions
// ---------------------------------------------------------------------------

/** DORA performance classification per the Accelerate book */
export type DoraClassification = 'elite' | 'high' | 'medium' | 'low';

/** DORA four key metrics snapshot */
export interface DoraMetrics {
  /** Deployment frequency — deploys per day/week */
  deploymentFrequency: number;
  deploymentFrequencyUnit: 'daily' | 'weekly' | 'monthly';
  deploymentFrequencyClassification: DoraClassification;

  /** Lead time for changes — median time from commit to production (hours) */
  leadTimeForChanges: number;
  leadTimeForChangesClassification: DoraClassification;

  /** Mean time to restore service (hours) */
  meanTimeToRestore: number;
  meanTimeToRestoreClassification: DoraClassification;

  /** Change failure rate — percentage of deployments causing failure */
  changeFailureRate: number;
  changeFailureRateClassification: DoraClassification;

  /** Overall DORA classification (lowest of the four) */
  overallClassification: DoraClassification;

  /** Period boundaries */
  periodStart: string;
  periodEnd: string;
  teamId: string;
}

/** A single phase within the cycle time breakdown */
export interface CycleTimePhase {
  name: string;
  /** Duration in hours */
  duration: number;
  /** Percentage of total cycle time */
  percentage: number;
}

/** Full cycle time breakdown for a team/period */
export interface CycleTimeBreakdown {
  teamId: string;
  periodStart: string;
  periodEnd: string;
  /** Total median cycle time in hours */
  totalMedian: number;
  /** p85 cycle time in hours */
  totalP85: number;
  phases: CycleTimePhase[];
}

/** Lead time distribution data point (for scatter plots / histograms) */
export interface LeadTimeDistribution {
  teamId: string;
  periodStart: string;
  periodEnd: string;
  /** Individual data points — lead time in hours per item */
  dataPoints: Array<{
    id: string;
    title: string;
    leadTimeHours: number;
    closedAt: string;
  }>;
  /** Statistical summary */
  median: number;
  p85: number;
  p95: number;
  average: number;
}

/** Throughput data — items completed per time bucket */
export interface ThroughputData {
  teamId: string;
  periodStart: string;
  periodEnd: string;
  bucketSize: 'daily' | 'weekly';
  buckets: Array<{
    date: string;
    count: number;
  }>;
  averageThroughput: number;
}

/** Sprint overview metrics */
export interface SprintOverview {
  sprintId: string;
  sprintName: string;
  teamId: string;
  startDate: string;
  endDate: string;
  /** Story points or issue count */
  planned: number;
  completed: number;
  added: number;
  removed: number;
  /** Completion rate as percentage */
  completionRate: number;
  /** Scope change percentage */
  scopeChange: number;
  /** Carry-over from previous sprint */
  carryOver: number;
}

/** Pull request summary for a team/period */
export interface PullRequestSummary {
  teamId: string;
  periodStart: string;
  periodEnd: string;
  totalOpened: number;
  totalMerged: number;
  totalClosed: number;
  /** Median time to merge in hours */
  medianTimeToMerge: number;
  /** Median time to first review in hours */
  medianTimeToFirstReview: number;
  /** Average review cycles per PR */
  averageReviewCycles: number;
  /** PRs with no reviews */
  prsWithoutReview: number;
}

/** Generic metric trend over time */
export interface MetricTrend {
  metricName: string;
  teamId: string;
  dataPoints: Array<{
    date: string;
    value: number;
  }>;
  /** Direction of change */
  trend: 'improving' | 'stable' | 'declining';
  /** Percentage change over the period */
  changePercent: number;
}

/** Work in progress status */
export interface WipStatus {
  teamId: string;
  timestamp: string;
  /** Current WIP count */
  currentWip: number;
  /** Recommended WIP limit */
  wipLimit: number;
  /** Whether current WIP exceeds limit */
  isOverLimit: boolean;
  /** WIP by status/column */
  byStatus: Array<{
    status: string;
    count: number;
  }>;
  /** WIP aging — items above threshold */
  agingItems: Array<{
    id: string;
    title: string;
    status: string;
    ageInDays: number;
  }>;
}
