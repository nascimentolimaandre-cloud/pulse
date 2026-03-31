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
  BenchmarkThresholds,
  CycleTimeBreakdown,
  CycleTimePhase,
  ThroughputResponse,
  ThroughputDataPoint,
  ThroughputAnalytics,
  PrSizeDistributionItem,
} from '@/types/metrics';

/* ── Helpers ── */

const NO_DATA_TREND: MetricTrend = {
  direction: 'flat',
  percentage: 0,
  isPositive: true,
  hasHistoricalData: false,
};

function safeNumber(value: unknown, fallback = 0): number {
  if (value === null || value === undefined) return fallback;
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function mapTrendDirection(
  direction: string | null | undefined,
): MetricTrend['direction'] {
  if (direction === 'up') return 'up';
  if (direction === 'down') return 'down';
  return 'flat';
}

/**
 * Build a MetricTrend from API trend fields.
 * @param trendPct - % change from API (null = no historical data)
 * @param trendDir - direction from API
 * @param polarity - which direction is "good" for this metric
 */
function buildTrendFromApi(
  trendPct: number | null | undefined,
  trendDir: string | null | undefined,
  polarity: 'higher-is-better' | 'lower-is-better',
): MetricTrend {
  if (trendPct === null || trendPct === undefined) {
    return { ...NO_DATA_TREND };
  }

  const direction = mapTrendDirection(trendDir);
  const absPct = Math.abs(Math.round(trendPct * 10) / 10);

  // "isPositive" means the change is good for the team
  let isPositive: boolean;
  if (direction === 'flat') {
    isPositive = true;
  } else if (polarity === 'higher-is-better') {
    isPositive = direction === 'up';
  } else {
    isPositive = direction === 'down';
  }

  return {
    direction,
    percentage: absPct,
    isPositive,
    hasHistoricalData: true,
  };
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
  if (nonZero.length < 2) return { ...NO_DATA_TREND };

  const recent = nonZero[nonZero.length - 1]!;
  const previous = nonZero[nonZero.length - 2]!;
  if (previous === 0) return { ...NO_DATA_TREND };

  const pctChange = Math.round(((recent - previous) / previous) * 100);
  const dir: MetricTrend['direction'] =
    pctChange > 5 ? 'up' : pctChange < -5 ? 'down' : 'flat';

  const isPositive =
    polarity === 'higher-is-better'
      ? dir === 'up' || dir === 'flat'
      : dir === 'down' || dir === 'flat';

  return { direction: dir, percentage: Math.abs(pctChange), isPositive, hasHistoricalData: true };
}

function mapClassification(
  level: string | null | undefined,
): DoraClassification {
  if (level === 'elite' || level === 'high' || level === 'medium' || level === 'low') {
    return level;
  }
  return 'low';
}

/* ── Benchmark definitions (DORA 2023 State of DevOps Report) ── */

const BENCHMARKS: Record<string, BenchmarkThresholds> = {
  deployment_frequency: {
    elite: '\u2265 1/day',
    high: '\u2265 1/week',
    medium: '\u2265 1/month',
    low: '< 1/month',
  },
  lead_time: {
    elite: '< 1 hour',
    high: '< 1 week',
    medium: '< 1 month',
    low: '\u2265 1 month',
  },
  change_failure_rate: {
    elite: '< 5%',
    high: '< 10%',
    medium: '< 15%',
    low: '> 15%',
  },
  cycle_time: {
    elite: '< 2h',
    high: '< 24h',
    medium: '< 72h',
    low: '\u2265 72h',
  },
  wip: {
    elite: '\u2264 3',
    high: '\u2264 6',
    medium: '\u2264 10',
    low: '> 10',
  },
  throughput: {
    elite: '\u2265 50/wk',
    high: '\u2265 20/wk',
    medium: '\u2265 5/wk',
    low: '< 5/wk',
  },
};

/* ── Classification helpers for non-DORA metrics ── */

function classifyCycleTime(hours: number): DoraClassification {
  if (hours < 2) return 'elite';
  if (hours < 24) return 'high';
  if (hours < 72) return 'medium';
  return 'low';
}

function classifyWip(count: number): DoraClassification {
  if (count <= 3) return 'elite';
  if (count <= 6) return 'high';
  if (count <= 10) return 'medium';
  return 'low';
}

function classifyThroughput(total: number, periodDays: number): DoraClassification {
  const perWeek = (total / Math.max(periodDays, 1)) * 7;
  if (perWeek >= 50) return 'elite';
  if (perWeek >= 20) return 'high';
  if (perWeek >= 5) return 'medium';
  return 'low';
}

function periodToDays(period: string): number {
  const match = period.match(/^(\d+)d$/);
  return match ? parseInt(match[1]!, 10) : 30;
}

/* ── Raw API shapes (snake_case) ── */

interface RawHomeMetricItem {
  value: number | null;
  unit: string | null;
  level: string | null;
  trend_direction: string | null;
  trend_percentage: number | null;
  previous_value: number | null;
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
  polarity: 'higher-is-better' | 'lower-is-better',
  benchmarkKey: string,
): DoraMetricItem {
  return {
    label,
    value: round2(safeNumber(raw.value)),
    unit: raw.unit ?? '',
    trend: buildTrendFromApi(raw.trend_percentage, raw.trend_direction, polarity),
    classification: mapClassification(raw.level),
    sparklineData: [],
    benchmarks: BENCHMARKS[benchmarkKey],
  };
}

export function transformHomeMetrics(raw: RawHomeResponse): HomeMetrics {
  const d = raw.data;
  const days = periodToDays(raw.period);

  // CFR: convert ratio (0-1) to percentage display
  const cfrItem = buildDoraMetricItem(d.change_failure_rate, 'Change Failure Rate', 'lower-is-better', 'change_failure_rate');
  cfrItem.value = round2(safeNumber(d.change_failure_rate.value) * 100);
  cfrItem.unit = '%';

  // Non-DORA metrics: classify locally
  const ctValue = round2(safeNumber(d.cycle_time.value));
  const wipValue = safeNumber(d.wip.value);
  const tpValue = safeNumber(d.throughput.value);

  return {
    deploymentFrequency: buildDoraMetricItem(
      d.deployment_frequency,
      'Deployment Frequency',
      'higher-is-better',
      'deployment_frequency',
    ),
    leadTimeForChanges: buildDoraMetricItem(
      d.lead_time,
      'Lead Time for Changes',
      'lower-is-better',
      'lead_time',
    ),
    changeFailureRate: cfrItem,
    cycleTime: {
      label: 'Cycle Time',
      value: ctValue,
      unit: d.cycle_time.unit ?? 'hours',
      trend: buildTrendFromApi(d.cycle_time.trend_percentage, d.cycle_time.trend_direction, 'lower-is-better'),
      classification: classifyCycleTime(ctValue),
      sparklineData: [],
      benchmarks: BENCHMARKS['cycle_time'],
    },
    wipCount: {
      label: 'Work in Progress',
      value: wipValue,
      unit: d.wip.unit ?? 'items',
      trend: buildTrendFromApi(d.wip.trend_percentage, d.wip.trend_direction, 'lower-is-better'),
      classification: classifyWip(wipValue),
      sparklineData: [],
      benchmarks: BENCHMARKS['wip'],
    },
    throughput: {
      label: 'Throughput',
      value: tpValue,
      unit: d.throughput.unit ?? 'PRs merged',
      trend: buildTrendFromApi(d.throughput.trend_percentage, d.throughput.trend_direction, 'higher-is-better'),
      classification: classifyThroughput(tpValue, days),
      sparklineData: [],
      benchmarks: BENCHMARKS['throughput'],
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
