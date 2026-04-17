/**
 * TEMP mock derivation for per-team ranking + evolution.
 *
 * The backend endpoints below do not yet exist. Until pulse-data-engineer
 * exposes them, we derive deterministic synthetic metrics from the real
 * TeamHealth[] returned by `/data/v1/pipeline/teams` so the dashboard renders
 * at production scale (27 squads × 8 tribos).
 *
 * TODO(pulse-data-engineer): replace with real endpoints:
 *   - GET /data/v1/metrics/by-team?metric={}&period={}
 *   - GET /data/v1/metrics/by-team/evolution?metric={}&period={}
 *   - GET /data/v1/teams/{id}/detail?period={}
 *
 * Every consumer of the functions here should be swapped to the real hooks
 * once available (see `useMetrics.ts` TODO markers).
 */
import type { TeamHealth } from '@/types/pipeline';
import type { DashboardMetric } from '@/stores/filterStore';
import type { DoraClassification } from '@/types/metrics';
import { classifyMetric } from './classify';

export interface TeamRankingRow {
  teamId: string;
  name: string;
  tribe: string;
  value: number;
  classification: DoraClassification;
  status: 'healthy' | 'backfilling' | 'degraded' | 'error';
}

export interface TeamEvolutionSeries {
  teamId: string;
  name: string;
  tribe: string;
  points: number[]; // 12 weeks
  current: number;
  deltaPct: number;
  classification: DoraClassification;
}

export interface TeamDetailData {
  teamId: string;
  name: string;
  tribe: string;
  metrics: Record<DashboardMetric, { value: number; classification: DoraClassification; unit: string }>;
  cycleTimeP50: number;
  cycleTimeP85: number;
  evolution: Record<DashboardMetric, number[]>;
}

/** Deterministic PRNG — mulberry32 */
function prng(seed: number) {
  return () => {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Hash team id to a stable seed */
function teamSeed(teamId: string): number {
  let h = 0;
  for (let i = 0; i < teamId.length; i++) {
    h = (h * 31 + teamId.charCodeAt(i)) | 0;
  }
  return Math.abs(h) || 1;
}

/** Classification bias based on team health status (keeps ranking realistic) */
function healthBand(status: TeamHealth['health']): 'elite' | 'high' | 'medium' | 'low' {
  if (status === 'healthy') return 'high';
  if (status === 'backfilling') return 'medium';
  if (status === 'degraded') return 'medium';
  return 'low';
}

/** Ranges per metric × classification band */
const BANDS: Record<
  DashboardMetric,
  Record<'elite' | 'high' | 'medium' | 'low', [number, number]>
> = {
  deployFreq: {
    elite: [3.0, 6.0],
    high: [1.2, 3.0],
    medium: [0.4, 1.2],
    low: [0.05, 0.4],
  },
  leadTime: {
    elite: [8, 22],
    high: [22, 50],
    medium: [50, 120],
    low: [120, 360],
  },
  cfr: {
    elite: [1, 5],
    high: [5, 10],
    medium: [10, 15],
    low: [15, 40],
  },
  cycleTime: {
    elite: [1.5, 3.0],
    high: [2.5, 5.0],
    medium: [4.0, 7.0],
    low: [6.0, 12],
  },
  wip: {
    elite: [8, 16],
    high: [12, 22],
    medium: [18, 30],
    low: [25, 45],
  },
  throughput: {
    elite: [18, 30],
    high: [12, 22],
    medium: [8, 15],
    low: [3, 10],
  },
};

function pick(rng: () => number, range: [number, number], integer = false): number {
  const lo = range[0];
  const hi = range[1];
  const v = lo + rng() * (hi - lo);
  if (integer) return Math.round(v);
  return Math.round(v * 10) / 10;
}

/** Deterministic single metric value for a team */
export function deriveTeamValue(team: TeamHealth, metric: DashboardMetric, offset = 0): number {
  const band = healthBand(team.health);
  // Nudge by first char of squadKey so tribes differ
  const seed = teamSeed(team.id + metric + offset);
  const rng = prng(seed);
  const range = BANDS[metric][band];
  const integer = metric === 'leadTime' || metric === 'wip' || metric === 'throughput';
  return pick(rng, range, integer);
}

export function deriveRanking(
  teams: TeamHealth[],
  metric: DashboardMetric,
): TeamRankingRow[] {
  return teams.map((t) => {
    const value = deriveTeamValue(t, metric);
    return {
      teamId: t.id,
      name: t.name,
      tribe: t.tribe ?? '—',
      value,
      classification: classifyMetric(metric, value),
      status: t.health,
    };
  });
}

export function deriveEvolution(
  teams: TeamHealth[],
  metric: DashboardMetric,
): TeamEvolutionSeries[] {
  return teams.map((t) => {
    const baseline = deriveTeamValue(t, metric);
    const rng = prng(teamSeed(t.id + metric + '-evo'));
    const points: number[] = [];
    let v = baseline * 0.92;
    for (let i = 0; i < 12; i++) {
      v = v + (baseline - v) * 0.25 + (rng() - 0.5) * baseline * 0.12;
      points.push(Math.max(0, Math.round(v * 100) / 100));
    }
    points[points.length - 1] = baseline;
    const current = baseline;
    const first: number = points[0] ?? baseline;
    const deltaPct = first > 0 ? ((current - first) / first) * 100 : 0;
    return {
      teamId: t.id,
      name: t.name,
      tribe: t.tribe ?? '—',
      points,
      current,
      deltaPct,
      classification: classifyMetric(metric, current),
    };
  });
}

const ALL_METRICS: DashboardMetric[] = [
  'deployFreq',
  'leadTime',
  'cfr',
  'cycleTime',
  'wip',
  'throughput',
];

const METRIC_UNITS: Record<DashboardMetric, string> = {
  deployFreq: '/dia',
  leadTime: 'h',
  cfr: '%',
  cycleTime: 'd',
  wip: 'itens',
  throughput: 'PRs/sem',
};

export function deriveTeamDetail(team: TeamHealth): TeamDetailData {
  const metrics = {} as TeamDetailData['metrics'];
  const evolution = {} as TeamDetailData['evolution'];

  for (const m of ALL_METRICS) {
    const value = deriveTeamValue(team, m);
    metrics[m] = {
      value,
      classification: classifyMetric(m, value),
      unit: METRIC_UNITS[m],
    };
    // Inline evolution derivation (same as deriveEvolution but single team)
    const rng = prng(teamSeed(team.id + m + '-evo'));
    const pts: number[] = [];
    let v = value * 0.92;
    for (let i = 0; i < 12; i++) {
      v = v + (value - v) * 0.25 + (rng() - 0.5) * value * 0.12;
      pts.push(Math.max(0, Math.round(v * 100) / 100));
    }
    pts[pts.length - 1] = value;
    evolution[m] = pts;
  }

  const cycleTimeP50 = metrics.cycleTime?.value ?? 0;
  const cycleTimeP85 = Math.round(cycleTimeP50 * 2.7 * 10) / 10;

  return {
    teamId: team.id,
    name: team.name,
    tribe: team.tribe ?? '—',
    metrics,
    cycleTimeP50,
    cycleTimeP85,
    evolution,
  };
}
