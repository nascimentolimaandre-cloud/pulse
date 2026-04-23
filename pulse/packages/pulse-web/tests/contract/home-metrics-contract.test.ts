/**
 * Sample 3 — Contract test: HomeMetrics response schema (Zod)
 *
 * Validates that the frontend's Zod schema correctly describes what the backend
 * must return. This is NOT an end-to-end call — it validates the contract
 * mechanism itself using a local fixture.
 *
 * Why this matters:
 *  - When backend adds/removes fields, the schema parse fails here BEFORE any
 *    runtime crash in production.
 *  - Serves as living documentation of the frontend's structural expectations.
 *
 * Pattern: define a minimal Zod schema that mirrors the critical fields the
 * frontend consumes, then parse against fixtures. The schema intentionally
 * covers only the fields that, if missing, would break the UI.
 */
import { z } from 'zod';

// ── Minimal Zod schema — mirrors what transformHomeMetrics expects ────────────
//
// We only validate fields the frontend READS. Optional fields that the backend
// may add without breaking the frontend are not listed here.

const MetricItemSchema = z.object({
  value: z.number().nullable(),
  unit: z.string().nullable(),
  level: z.string().nullable(),
  trend_direction: z.string().nullable(),
  trend_percentage: z.number().nullable(),
  previous_value: z.number().nullable(),
});

const LeadTimeCoverageSchema = z.object({
  covered: z.number(),
  total: z.number(),
  pct: z.number(),
});

const LeadTimeStrictSchema = MetricItemSchema.extend({
  coverage: LeadTimeCoverageSchema.nullable().optional(),
});

const HomeMetricsResponseSchema = z.object({
  period: z.string(),
  period_start: z.string(),
  period_end: z.string(),
  team_id: z.string().nullable(),
  calculated_at: z.string(),
  data: z.object({
    deployment_frequency: MetricItemSchema,
    lead_time: MetricItemSchema,
    // lead_time_strict is optional — backend may omit on older snapshots
    lead_time_strict: LeadTimeStrictSchema.optional(),
    change_failure_rate: MetricItemSchema,
    cycle_time: MetricItemSchema,
    cycle_time_p85: MetricItemSchema,
    time_to_restore: MetricItemSchema,
    wip: MetricItemSchema,
    throughput: MetricItemSchema,
    overall_dora_level: z.string().nullable(),
  }),
});

// ── Fixtures ─────────────────────────────────────────────────────────────────

const VALID_RESPONSE = {
  period: '60d',
  period_start: '2026-02-22',
  period_end: '2026-04-23',
  team_id: null,
  calculated_at: '2026-04-23T10:00:00Z',
  data: {
    deployment_frequency: {
      value: 3.2,
      unit: 'deploys/day',
      level: 'high',
      trend_direction: 'up',
      trend_percentage: 10,
      previous_value: 2.9,
    },
    lead_time: {
      value: 48.5,
      unit: 'hours',
      level: 'high',
      trend_direction: 'down',
      trend_percentage: -5,
      previous_value: 51.0,
    },
    lead_time_strict: {
      value: 52.3,
      unit: 'hours',
      level: 'high',
      trend_direction: 'flat',
      trend_percentage: 0,
      previous_value: 52.3,
      coverage: { covered: 80, total: 100, pct: 0.8 },
    },
    change_failure_rate: {
      value: 0.04,
      unit: '%',
      level: 'elite',
      trend_direction: 'down',
      trend_percentage: -1,
      previous_value: 0.05,
    },
    cycle_time: {
      value: 12.5,
      unit: 'hours',
      level: 'high',
      trend_direction: 'down',
      trend_percentage: -8,
      previous_value: 13.6,
    },
    cycle_time_p85: {
      value: 28.0,
      unit: 'hours',
      level: 'medium',
      trend_direction: 'flat',
      trend_percentage: 0,
      previous_value: 28.0,
    },
    time_to_restore: {
      value: null,
      unit: 'hours',
      level: null,
      trend_direction: null,
      trend_percentage: null,
      previous_value: null,
    },
    wip: {
      value: 8,
      unit: 'items',
      level: 'high',
      trend_direction: 'down',
      trend_percentage: -2,
      previous_value: 10,
    },
    throughput: {
      value: 120,
      unit: 'PRs merged',
      level: 'elite',
      trend_direction: 'up',
      trend_percentage: 5,
      previous_value: 114,
    },
    overall_dora_level: 'high',
  },
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('HomeMetrics response contract (Zod)', () => {
  it('validates a structurally correct response without errors', () => {
    const result = HomeMetricsResponseSchema.safeParse(VALID_RESPONSE);

    expect(result.success).toBe(true);
  });

  it('rejects a response missing the required lead_time field', () => {
    const { lead_time: _removed, ...dataWithoutLeadTime } = VALID_RESPONSE.data;
    const invalidResponse = {
      ...VALID_RESPONSE,
      data: dataWithoutLeadTime,
    };

    const result = HomeMetricsResponseSchema.safeParse(invalidResponse);

    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p.includes('lead_time'))).toBe(true);
    }
  });

  it('rejects a response where throughput.value is a string instead of number', () => {
    const invalidResponse = {
      ...VALID_RESPONSE,
      data: {
        ...VALID_RESPONSE.data,
        throughput: {
          ...VALID_RESPONSE.data.throughput,
          value: 'one hundred twenty', // wrong type — must be number | null
        },
      },
    };

    const result = HomeMetricsResponseSchema.safeParse(invalidResponse);

    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p.includes('throughput'))).toBe(true);
    }
  });
});
