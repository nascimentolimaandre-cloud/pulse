/**
 * Contract tests: GET /data/v1/metrics/lean (LeanResponse)
 *
 * Validates that the Zod schema correctly describes the wire contract for the
 * Lean metrics endpoint. Tests use synthetic fixtures.
 *
 * Key insight: all data fields are opaque lists/dicts or a scalar int. The
 * frontend transforms these into CfdDataPoint[], ScatterplotDataPoint[], etc.
 * The contract only needs to validate the wire shape — not the transformed shape.
 *
 * Test plan:
 *   A. Valid well-formed response parses correctly
 *   B. Missing required `data` field is rejected
 *   C. Type mismatch (wip as string instead of integer) is rejected
 *   D. Anti-surveillance: forbidden fields at data level are absent from schema
 *   E. (skip if offline) Real API response parses successfully
 */

import { describe, it, expect } from 'vitest';
import { LeanResponseSchema } from './schemas/lean.schema';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const VALID_CFD_POINTS = [
  { date: '2026-03-31', backlog: 120, todo: 30, in_progress: 15, review: 5, done: 800 },
  { date: '2026-04-07', backlog: 118, todo: 28, in_progress: 17, review: 4, done: 860 },
  { date: '2026-04-14', backlog: 115, todo: 25, in_progress: 14, review: 6, done: 920 },
  { date: '2026-04-21', backlog: 112, todo: 22, in_progress: 16, review: 3, done: 975 },
];

const VALID_LEAD_TIME_DIST = {
  p50: 8.2,
  p85: 18.5,
  p95: 32.0,
  histogram: [
    { bucket: '0-4d', count: 42 },
    { bucket: '4-8d', count: 58 },
    { bucket: '8-16d', count: 35 },
    { bucket: '16d+', count: 12 },
  ],
};

const VALID_THROUGHPUT_POINTS = [
  { week: '2026-03-31', count: 52 },
  { week: '2026-04-07', count: 48 },
  { week: '2026-04-14', count: 61 },
  { week: '2026-04-21', count: 44 },
];

const VALID_SCATTERPLOT = {
  points: [
    { id: 'OKM-1234', lead_time_days: 6.5, closed_at: '2026-04-20T10:00:00Z', is_outlier: false },
    { id: 'FID-567', lead_time_days: 28.0, closed_at: '2026-04-15T14:00:00Z', is_outlier: true },
  ],
  p50: 8.2,
  p85: 18.5,
  p95: 32.0,
};

const VALID_LEAN_RESPONSE = {
  period: '30d',
  period_start: '2026-03-24T00:00:00+00:00',
  period_end: '2026-04-23T00:00:00+00:00',
  team_id: null,
  calculated_at: '2026-04-23T10:00:00+00:00',
  data: {
    cfd: VALID_CFD_POINTS,
    wip: 18,
    lead_time_distribution: VALID_LEAD_TIME_DIST,
    throughput: VALID_THROUGHPUT_POINTS,
    scatterplot: VALID_SCATTERPLOT,
  },
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('LeanResponse contract (Zod)', () => {
  it('A: validates a well-formed response with all sub-metrics present', () => {
    const result = LeanResponseSchema.safeParse(VALID_LEAN_RESPONSE);
    expect(result.success).toBe(true);
  });

  it('A2: validates when all data fields are null (no snapshots yet)', () => {
    const response = {
      ...VALID_LEAN_RESPONSE,
      calculated_at: null,
      data: {
        cfd: null,
        wip: null,
        lead_time_distribution: null,
        throughput: null,
        scatterplot: null,
      },
    };
    const result = LeanResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('A3: validates empty data object (fallback path)', () => {
    const response = {
      ...VALID_LEAN_RESPONSE,
      calculated_at: null,
      data: {},
    };
    const result = LeanResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('A4: validates wip=0 (zero WIP is a valid state)', () => {
    const response = {
      ...VALID_LEAN_RESPONSE,
      data: { ...VALID_LEAN_RESPONSE.data, wip: 0 },
    };
    const result = LeanResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('B: rejects response missing the required `data` field', () => {
     
    const { data: _removed, ...withoutData } = VALID_LEAN_RESPONSE;
    const result = LeanResponseSchema.safeParse(withoutData);
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p === 'data')).toBe(true);
    }
  });

  it('C: rejects `wip` as a string instead of integer', () => {
    const response = {
      ...VALID_LEAN_RESPONSE,
      data: {
        ...VALID_LEAN_RESPONSE.data,
        wip: 'eighteen', // wrong type
      },
    };
    const result = LeanResponseSchema.safeParse(response);
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p.includes('wip'))).toBe(true);
    }
  });

  it('C2: rejects `cfd` as an object instead of an array', () => {
    const response = {
      ...VALID_LEAN_RESPONSE,
      data: {
        ...VALID_LEAN_RESPONSE.data,
        cfd: { date: '2026-04-01', count: 100 }, // wrong type — must be array
      },
    };
    const result = LeanResponseSchema.safeParse(response);
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p.includes('cfd'))).toBe(true);
    }
  });

  it('D: anti-surveillance — schema declares no `assignee` or `author` field in data', () => {
    // Lean data is entirely opaque (list[dict] or dict) — there are no
    // declared individual-level fields. The schema's own shape has no
    // forbidden keys. The meta-test in anti-surveillance-schemas.test.ts
    // validates this formally. Here we verify injected keys at root level
    // are absent from the schema's OWN declared keys.
    const dataKeys = Object.keys(
      (LeanResponseSchema.shape as { data: { shape: Record<string, unknown> } }).data.shape,
    );
    const forbidden = dataKeys.filter((k) =>
      /^(assignee|author|reporter|developer|committer|user|login|email)/i.test(k),
    );
    expect(forbidden).toEqual([]);
  });

  it('E: (skip if backend offline) parses real API response', async () => {
    let backendAvailable = false;
    try {
      const response = await fetch(
        'http://localhost:8000/data/v1/metrics/lean?period=30d',
        { signal: AbortSignal.timeout(2000) },
      );
      backendAvailable = response.ok;
    } catch {
      backendAvailable = false;
    }

    if (!backendAvailable) {
      console.info('[contract/lean] Backend not available — skipping live test');
      return;
    }

    const response = await fetch('http://localhost:8000/data/v1/metrics/lean?period=30d');
    const json = await response.json();
    const result = LeanResponseSchema.safeParse(json);
    if (!result.success) {
      console.error('[contract/lean] Schema mismatch:', result.error.issues);
    }
    expect(result.success).toBe(true);
  });
});
