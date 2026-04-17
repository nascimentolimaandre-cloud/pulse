/**
 * DORA + Flow classification helpers (frontend fallback).
 *
 * TODO(pulse-data-scientist): Flow thresholds (cycleTime / WIP / throughput)
 * are heuristic here and must be validated with Webmotors baseline before R1.
 * See: pulse/docs/metrics/classification.md
 */
import type { DoraClassification } from '@/types/metrics';
import type { DashboardMetric } from '@/stores/filterStore';

// DORA 2023 thresholds
const DORA_THRESHOLDS = {
  deployFreq: { elite: 1, high: 0.14, medium: 0.03 }, // per day
  leadTime: { elite: 24, high: 168, medium: 720 }, // hours (<= is better)
  cfr: { elite: 5, high: 10, medium: 15 }, // % (<= is better)
} as const;

export function classifyMetric(
  metric: DashboardMetric,
  value: number,
): DoraClassification {
  if (metric === 'deployFreq') {
    const t = DORA_THRESHOLDS.deployFreq;
    if (value >= t.elite) return 'elite';
    if (value >= t.high) return 'high';
    if (value >= t.medium) return 'medium';
    return 'low';
  }
  if (metric === 'leadTime') {
    const t = DORA_THRESHOLDS.leadTime;
    if (value <= t.elite) return 'elite';
    if (value <= t.high) return 'high';
    if (value <= t.medium) return 'medium';
    return 'low';
  }
  if (metric === 'cfr') {
    const t = DORA_THRESHOLDS.cfr;
    if (value <= t.elite) return 'elite';
    if (value <= t.high) return 'high';
    if (value <= t.medium) return 'medium';
    return 'low';
  }
  if (metric === 'cycleTime') {
    if (value < 3) return 'elite';
    if (value < 5) return 'high';
    if (value < 8) return 'medium';
    return 'low';
  }
  if (metric === 'wip') {
    if (value < 15) return 'elite';
    if (value < 22) return 'high';
    if (value < 30) return 'medium';
    return 'low';
  }
  if (metric === 'throughput') {
    if (value >= 20) return 'elite';
    if (value >= 14) return 'high';
    if (value >= 9) return 'medium';
    return 'low';
  }
  return 'low';
}

export const METRIC_META: Record<
  DashboardMetric,
  {
    label: string;
    title: string;
    sub: string;
    unit: string;
    sortDir: 'asc' | 'desc';
    lowerIsBetter: boolean;
  }
> = {
  deployFreq: {
    label: 'Deploy Frequency',
    title: 'Deploy Frequency por squad',
    sub: 'Deploys por dia · maior é melhor',
    unit: '/dia',
    sortDir: 'desc',
    lowerIsBetter: false,
  },
  leadTime: {
    label: 'Lead Time',
    title: 'Lead Time por squad',
    sub: 'Horas commit → produção · menor é melhor',
    unit: 'h',
    sortDir: 'asc',
    lowerIsBetter: true,
  },
  cfr: {
    label: 'Change Failure',
    title: 'Change Failure Rate por squad',
    sub: '% de deploys com falha · menor é melhor',
    unit: '%',
    sortDir: 'asc',
    lowerIsBetter: true,
  },
  cycleTime: {
    label: 'Cycle Time',
    title: 'Cycle Time P50 por squad',
    sub: 'Dias · menor é melhor',
    unit: 'd',
    sortDir: 'asc',
    lowerIsBetter: true,
  },
  wip: {
    label: 'WIP',
    title: 'Work in Progress por squad',
    sub: 'Itens em progresso · menor é mais saudável',
    unit: 'itens',
    sortDir: 'asc',
    lowerIsBetter: true,
  },
  throughput: {
    label: 'Throughput',
    title: 'Throughput por squad',
    sub: 'PRs por semana · maior é melhor',
    unit: 'PRs/sem',
    sortDir: 'desc',
    lowerIsBetter: false,
  },
};

export function classifLabel(c: DoraClassification): string {
  return { elite: 'Elite', high: 'High', medium: 'Medium', low: 'Low' }[c];
}
