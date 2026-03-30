/**
 * Transform functions that map FastAPI snake_case responses
 * to the camelCase frontend TypeScript types.
 *
 * Each transform provides sensible defaults for null values
 * and generates sparkline data from trend arrays.
 */
import type {
  HomeMetrics,
  MetricTrend,
  DoraMetricItem,
  DoraClassification,
  CycleTimeBreakdown,
  CycleTimePhase,
  ThroughputResponse,
  ThroughputDataPoint,
  ThroughputAnalytics,
  PrSizeDistributionItem,
} from '@/types/metrics';

/* ── Helpers ── */

const FLAT_TREND: MetricTrend = {
  direction: 'flat',
  percentage: 0,
  isPositive: true,
};

function safeNumber(value: unknown, fallback = 0): number {
  if (value === null || value === undefined) return fallback;
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function mapTrendDirection(
  direction: string | null | undefined,
): MetricTrend['direction'] {
  if (direction === 'up') return 'up';
  if (direction === 'down') return 'down';
  return 'flat';
}

/**
 * Compute a MetricTrend from the last two non-zero values of a sparkline.
 * @param data - Array of numeric values (e.g. weekly p50 hours)
 * @param polarity - 'higher-is-better' (throughput) or 'lower-is-better' (cycle time)
 */
function computeTrend(
  data: number[],
  polarity: 'higher-is-better' | 'lower-is-better',
): MetricTrend {
  const nonZero = data.filter((v) => v > 0);
  if (nonZero.length < 2) return { ...FLAT_TREND };

  const recent = nonZero[nonZero.length - 1]!;
  const previous = nonZero[nonZero.length - 2]!;
  if (previous === 0) return { ...FLAT_TREND };

  const pctChange = Math.round(((recent - previous) / previous) * 100);
  const dir: MetricTrend['direction'] =
    pctChange > 5 ? 'up' : pctChange < -5 ? 'down' : 'flat';

  const isPositive =
    polarity === 'higher-is-better'
      ? dir === 'up' || dir === 'flat'
      : dir === 'down' || dir === 'flat';

  return { direction: dir, percentage: Math.abs(pctChange), isPositive };
}

function mapClassification(
  level: string | null | undefined,
): DoraClassification {
  if (level === 'elite' || level === 'high' || level === 'medium' || level === 'low') {
    return level;
  }
  return 'low';
}

/* ── Raw API shapes (snake_case) ── */

interface RawHomeMetricItem {
  value: number | null;
  unit: string | null;
  level: string | null;
  trend_direction: string | null;
}

interface RawHomeResponse {
  period: string;
  period_start: string;
  period_end: string;
  team_id: string | null;
  calculated_at: string;
  data: {
    deployment_frequency: RawHomeMetricItem;
    lead_time: RawHomeMetricItem;
    change_failure_rate: RawHomeMetricItem;
    cycle_time: RawHomeMetricItem;
    wip: RawHomeMetricItem;
    throughput: RawHomeMetricItem;
    overall_dora_level: string | null;
  };
}

interface RawCycleTimeTrendItem {
  week_start: string;
  p50_hours: number | null;
  p85_hours: number | null;
  merged_count: number;
}

interface RawCycleTimeResponse {
  period: string;
  data: {
    breakdown: {
      total_p50: number | null;
      total_p85: number | null;
      total_p95: number | null;
      coding_p50: number | null;
      pickup_p50: number | null;
      review_p50: number | null;
      deploy_p50: number | null;
      pr_count: number;
    };
    trend: RawCycleTimeTrendItem[];
  };
}

interface RawThroughputTrendItem {
  week_start: string;
  merged_count: number;
  opened_count: number;
}

interface RawRepoBreakdownItem {
  repo: string;
  merged_count: number;
}

interface RawSizeDistributionItem {
  size: string;
  count: number;
}

interface RawThroughputResponse {
  period: string;
  data: {
    trend: RawThroughputTrendItem[];
    pr_analytics: {
      total_merged: number;
      avg_time_to_merge_hours: number | null;
      repos_breakdown: RawRepoBreakdownItem[];
      size_distribution: RawSizeDistributionItem[];
    };
  };
}

/* ── Transforms ── */

function buildDoraMetricItem(
  raw: RawHomeMetricItem,
  label: string,
): DoraMetricItem {
  return {
    label,
    value: safeNumber(raw.value),
    unit: raw.unit ?? '',
    trend: {
      direction: mapTrendDirection(raw.trend_direction),
      percentage: 0,
      isPositive: true,
    },
    classification: mapClassification(raw.level),
    sparklineData: [],
  };
}

export function transformHomeMetrics(raw: RawHomeResponse): HomeMetrics {
  const d = raw.data;

  return {
    deploymentFrequency: buildDoraMetricItem(
      d.deployment_frequency,
      'Deployment Frequency',
    ),
    leadTimeForChanges: buildDoraMetricItem(d.lead_time, 'Lead Time for Changes'),
    changeFailureRate: buildDoraMetricItem(
      d.change_failure_rate,
      'Change Failure Rate',
    ),
    cycleTime: {
      label: 'Cycle Time',
      value: safeNumber(d.cycle_time.value),
      unit: d.cycle_time.unit ?? 'hours',
      trend: {
        direction: mapTrendDirection(d.cycle_time.trend_direction),
        percentage: 0,
        isPositive: true,
      },
      sparklineData: [],
    },
    wipCount: {
      label: 'Work in Progress',
      value: safeNumber(d.wip.value),
      unit: d.wip.unit ?? 'items',
      trend: {
        direction: mapTrendDirection(d.wip.trend_direction),
        percentage: 0,
        isPositive: true,
      },
      sparklineData: [],
    },
    throughput: {
      label: 'Throughput',
      value: safeNumber(d.throughput.value),
      unit: d.throughput.unit ?? 'PRs merged',
      trend: {
        direction: mapTrendDirection(d.throughput.trend_direction),
        percentage: 0,
        isPositive: true,
      },
      sparklineData: [],
    },
    prsNeedingAttention: [],
    period: raw.period,
    teamId: raw.team_id ?? 'default',
  };
}

export function transformCycleTime(raw: RawCycleTimeResponse): CycleTimeBreakdown {
  const b = raw.data.breakdown;
  const trend = raw.data.trend ?? [];

  // Build phases from breakdown fields
  const phaseDefinitions: {
    name: string;
    value: number | null;
    color: string;
  }[] = [
    { name: 'Coding', value: b.coding_p50, color: '#6366F1' },
    { name: 'Pickup', value: b.pickup_p50, color: '#8B5CF6' },
    { name: 'Review', value: b.review_p50, color: '#EC4899' },
    { name: 'Deploy', value: b.deploy_p50, color: '#10B981' },
  ];

  const phases: CycleTimePhase[] = phaseDefinitions.map((def) => ({
    name: def.name,
    medianHours: safeNumber(def.value),
    color: def.color,
    isBottleneck: false,
  }));

  // Find bottleneck (phase with highest median hours, if any have data)
  const maxPhaseHours = Math.max(...phases.map((p) => p.medianHours));
  if (maxPhaseHours > 0) {
    const bottleneckIdx = phases.findIndex(
      (p) => p.medianHours === maxPhaseHours,
    );
    const bottleneck = phases[bottleneckIdx];
    if (bottleneckIdx >= 0 && bottleneck) {
      bottleneck.isBottleneck = true;
    }
  }

  // Sparkline from weekly p50 trend
  const sparklineData = trend
    .map((t) => safeNumber(t.p50_hours))
    .filter((v) => v > 0);

  // Compute trend direction from sparkline
  const metricTrend: MetricTrend = computeTrend(sparklineData, 'lower-is-better');

  return {
    totalMedianHours: safeNumber(b.total_p50),
    phases,
    trend: metricTrend,
    sparklineData,
    period: raw.period,
    teamId: 'default',
  };
}

export function transformThroughput(raw: RawThroughputResponse): ThroughputResponse {
  const trend = raw.data.trend ?? [];
  const analytics = raw.data.pr_analytics;

  // Weekly data points
  const weeklyData: ThroughputDataPoint[] = trend.map((t) => ({
    week: t.week_start,
    merged: safeNumber(t.merged_count),
    opened: safeNumber(t.opened_count),
  }));

  // Average merged per week
  const totalMerged = weeklyData.reduce((sum, w) => sum + w.merged, 0);
  const weeksWithData = weeklyData.filter((w) => w.merged > 0).length;
  const averageMergedPerWeek =
    weeksWithData > 0
      ? Math.round(totalMerged / weeksWithData)
      : safeNumber(analytics.total_merged);

  // Sparkline from merged counts
  const sparklineData = weeklyData.map((w) => w.merged);

  // Compute trend direction
  const metricTrend: MetricTrend = computeTrend(sparklineData, 'higher-is-better');

  // Size distribution
  const validSizes = new Set(['XS', 'S', 'M', 'L', 'XL']);
  const prSizeDistribution: PrSizeDistributionItem[] = (
    analytics.size_distribution ?? []
  )
    .filter((s) => validSizes.has(s.size))
    .map((s) => ({
      size: s.size as PrSizeDistributionItem['size'],
      count: safeNumber(s.count),
    }));

  const transformedAnalytics: ThroughputAnalytics = {
    avgPrSize: 0,
    avgFirstReviewTimeHours: 0,
    avgReviewTurnaroundHours: safeNumber(analytics.avg_time_to_merge_hours),
    prSizeDistribution,
  };

  return {
    weeklyData,
    averageMergedPerWeek,
    trend: metricTrend,
    sparklineData,
    analytics: transformedAnalytics,
    period: raw.period,
    teamId: 'default',
  };
}
