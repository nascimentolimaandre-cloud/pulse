/**
 * Contract tests: GET /data/v1/metrics/cycle-time (CycleTimeResponse)
 *
 * Validates that the Zod schema correctly describes the wire contract for the
 * cycle time breakdown endpoint. Tests use synthetic fixtures.
 *
 * Test plan:
 *   A. Valid well-formed response (with breakdown + trend) parses correctly
 *   B. Missing required `data` field is rejected
 *   C. Type mismatch (string where number expected in breakdown) is rejected
 *   D. Anti-surveillance: injecting `assignee` into breakdown is stripped
 *   E. (skip if offline) Real API response parses successfully
 */

import { describe, it, expect } from 'vitest';
import { CycleTimeResponseSchema } from './schemas/cycle-time.schema';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const VALID_BREAKDOWN = {
  coding_p50: 8.0,
  coding_p85: 16.0,
  coding_p95: 24.0,
  pickup_p50: 2.5,
  pickup_p85: 6.0,
  pickup_p95: 12.0,
  review_p50: 4.0,
  review_p85: 8.0,
  review_p95: 14.0,
  deploy_p50: null,
  deploy_p85: null,
  deploy_p95: null,
  total_p50: 18.5,
  total_p85: 36.0,
  total_p95: 56.0,
  bottleneck_phase: 'coding',
  pr_count: 147,
};

const VALID_TREND = [
  { period: '2026-04-01', p50: 17.0, p85: 34.0, p95: 52.0 },
  { period: '2026-04-08', p50: 18.5, p85: 36.0, p95: 56.0 },
];

const VALID_CYCLE_TIME_RESPONSE = {
  period: '30d',
  period_start: '2026-03-24T00:00:00+00:00',
  period_end: '2026-04-23T00:00:00+00:00',
  team_id: null,
  calculated_at: '2026-04-23T10:00:00+00:00',
  data: {
    breakdown: VALID_BREAKDOWN,
    trend: VALID_TREND,
  },
};

const EMPTY_DATA_RESPONSE = {
  period: '30d',
  period_start: null,
  period_end: '2026-04-23T00:00:00+00:00',
  team_id: null,
  calculated_at: null,
  data: {},
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CycleTimeResponse contract (Zod)', () => {
  it('A: validates a well-formed response with breakdown and trend', () => {
    const result = CycleTimeResponseSchema.safeParse(VALID_CYCLE_TIME_RESPONSE);
    expect(result.success).toBe(true);
  });

  it('A2: validates when breakdown is null (no PR data in period)', () => {
    const response = {
      ...VALID_CYCLE_TIME_RESPONSE,
      data: { breakdown: null, trend: null },
    };
    const result = CycleTimeResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('A3: validates empty data fallback (no snapshots found)', () => {
    const result = CycleTimeResponseSchema.safeParse(EMPTY_DATA_RESPONSE);
    expect(result.success).toBe(true);
  });

  it('A4: validates when all percentile fields are null (insufficient data)', () => {
    const response = {
      ...VALID_CYCLE_TIME_RESPONSE,
      data: {
        breakdown: {
          coding_p50: null,
          coding_p85: null,
          coding_p95: null,
          pickup_p50: null,
          pickup_p85: null,
          pickup_p95: null,
          review_p50: null,
          review_p85: null,
          review_p95: null,
          deploy_p50: null,
          deploy_p85: null,
          deploy_p95: null,
          total_p50: null,
          total_p85: null,
          total_p95: null,
          bottleneck_phase: null,
          pr_count: 0,
        },
        trend: null,
      },
    };
    const result = CycleTimeResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('B: rejects response missing the required `data` field', () => {
     
    const { data: _removed, ...withoutData } = VALID_CYCLE_TIME_RESPONSE;
    const result = CycleTimeResponseSchema.safeParse(withoutData);
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p === 'data')).toBe(true);
    }
  });

  it('C: rejects total_p50 as string instead of number', () => {
    const response = {
      ...VALID_CYCLE_TIME_RESPONSE,
      data: {
        ...VALID_CYCLE_TIME_RESPONSE.data,
        breakdown: {
          ...VALID_BREAKDOWN,
          total_p50: 'eighteen-point-five', // wrong type
        },
      },
    };
    const result = CycleTimeResponseSchema.safeParse(response);
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p.includes('total_p50'))).toBe(true);
    }
  });

  it('C2: rejects pr_count as float string (must be integer)', () => {
    const response = {
      ...VALID_CYCLE_TIME_RESPONSE,
      data: {
        ...VALID_CYCLE_TIME_RESPONSE.data,
        breakdown: {
          ...VALID_BREAKDOWN,
          pr_count: 'one hundred and forty-seven', // wrong type
        },
      },
    };
    const result = CycleTimeResponseSchema.safeParse(response);
    expect(result.success).toBe(false);
  });

  it('D: anti-surveillance — `assignee` injected into breakdown is stripped', () => {
    const responseWithAssignee = {
      ...VALID_CYCLE_TIME_RESPONSE,
      data: {
        ...VALID_CYCLE_TIME_RESPONSE.data,
        breakdown: {
          ...VALID_BREAKDOWN,
          assignee: 'developer@webmotors.com.br', // must be stripped
        },
      },
    };
    const result = CycleTimeResponseSchema.safeParse(responseWithAssignee);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(Object.keys(result.data.data.breakdown ?? {})).not.toContain('assignee');
    }
  });

  it('E: (skip if backend offline) parses real API response', async () => {
    let backendAvailable = false;
    try {
      const response = await fetch(
        'http://localhost:8000/data/v1/metrics/cycle-time?period=30d',
        { signal: AbortSignal.timeout(2000) },
      );
      backendAvailable = response.ok;
    } catch {
      backendAvailable = false;
    }

    if (!backendAvailable) {
      console.info('[contract/cycle-time] Backend not available — skipping live test');
      return;
    }

    const response = await fetch('http://localhost:8000/data/v1/metrics/cycle-time?period=30d');
    const json = await response.json();
    const result = CycleTimeResponseSchema.safeParse(json);
    if (!result.success) {
      console.error('[contract/cycle-time] Schema mismatch:', result.error.issues);
    }
    expect(result.success).toBe(true);
  });
});
