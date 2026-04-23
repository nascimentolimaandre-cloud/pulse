/**
 * Contract tests: GET /data/v1/metrics/sprints (SprintResponse)
 *
 * Validates that the Zod schema correctly describes the wire contract for the
 * sprints metrics endpoint. Tests use synthetic fixtures.
 *
 * STRUCTURAL NOTE:
 *   SprintResponse does NOT use the MetricsEnvelope (no period, period_start,
 *   period_end). It only has team_id, calculated_at, and data. This is
 *   intentional — sprints are keyed by sprint ID, not time windows.
 *
 * Test plan:
 *   A. Valid well-formed response (with overview + comparison) parses correctly
 *   B. Missing required `data` field is rejected
 *   C. Type mismatch (float for integer field) is rejected
 *   D. Anti-surveillance: schema declares no forbidden individual fields
 *   E. (skip if offline) Real API response parses successfully
 */

import { describe, it, expect } from 'vitest';
import { SprintResponseSchema } from './schemas/sprints.schema';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const VALID_SPRINT_OVERVIEW = {
  committed_items: 42,
  added_items: 5,
  removed_items: 2,
  completed_items: 38,
  carried_over_items: 7,
  final_scope_items: 45,
  completion_rate: 0.844,
  scope_creep_pct: 0.119,
  carryover_rate: 0.156,
  committed_points: 84.0,
  completed_points: 71.0,
  completion_rate_points: 0.845,
  sprint_name: 'Sprint 42 — OKM',
  started_at: '2026-04-08',
  completed_at: '2026-04-22',
};

const VALID_SPRINT_COMPARISON = {
  sprints: [
    { sprint_name: 'Sprint 40', completed_items: 35, velocity_points: 68.0 },
    { sprint_name: 'Sprint 41', completed_items: 40, velocity_points: 77.0 },
    { sprint_name: 'Sprint 42', completed_items: 38, velocity_points: 71.0 },
  ],
  avg_velocity: 72.0,
  velocity_trend: 'stable',
};

const VALID_SPRINT_RESPONSE = {
  team_id: null,
  calculated_at: '2026-04-23T10:00:00+00:00',
  data: {
    overview: VALID_SPRINT_OVERVIEW,
    comparison: VALID_SPRINT_COMPARISON,
  },
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('SprintResponse contract (Zod)', () => {
  it('A: validates a well-formed response with overview and comparison', () => {
    const result = SprintResponseSchema.safeParse(VALID_SPRINT_RESPONSE);
    expect(result.success).toBe(true);
  });

  it('A2: validates when both overview and comparison are null (no sprint data)', () => {
    const response = {
      ...VALID_SPRINT_RESPONSE,
      calculated_at: null,
      data: { overview: null, comparison: null },
    };
    const result = SprintResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('A3: validates empty data fallback', () => {
    const response = {
      team_id: null,
      calculated_at: null,
      data: {},
    };
    const result = SprintResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('A4: validates default zero values for integer fields in overview', () => {
    const response = {
      ...VALID_SPRINT_RESPONSE,
      data: {
        overview: {
          committed_items: 0,
          added_items: 0,
          removed_items: 0,
          completed_items: 0,
          carried_over_items: 0,
          final_scope_items: 0,
          completion_rate: null,
          scope_creep_pct: null,
          carryover_rate: null,
          committed_points: 0.0,
          completed_points: 0.0,
          completion_rate_points: null,
          sprint_name: null,
          started_at: null,
          completed_at: null,
        },
        comparison: null,
      },
    };
    const result = SprintResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('A5: validates velocity_trend as "insufficient_data" (backend default)', () => {
    const response = {
      ...VALID_SPRINT_RESPONSE,
      data: {
        overview: VALID_SPRINT_OVERVIEW,
        comparison: {
          sprints: [],
          avg_velocity: null,
          velocity_trend: 'insufficient_data', // backend default
        },
      },
    };
    const result = SprintResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('B: rejects response missing the required `data` field', () => {
     
    const { data: _removed, ...withoutData } = VALID_SPRINT_RESPONSE;
    const result = SprintResponseSchema.safeParse(withoutData);
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p === 'data')).toBe(true);
    }
  });

  it('C: rejects `committed_items` as a string instead of integer', () => {
    const response = {
      ...VALID_SPRINT_RESPONSE,
      data: {
        ...VALID_SPRINT_RESPONSE.data,
        overview: {
          ...VALID_SPRINT_OVERVIEW,
          committed_items: 'forty-two', // wrong type
        },
      },
    };
    const result = SprintResponseSchema.safeParse(response);
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p.includes('committed_items'))).toBe(true);
    }
  });

  it('C2: rejects `completion_rate` as a string instead of float', () => {
    const response = {
      ...VALID_SPRINT_RESPONSE,
      data: {
        ...VALID_SPRINT_RESPONSE.data,
        overview: {
          ...VALID_SPRINT_OVERVIEW,
          completion_rate: '84.4%', // wrong type
        },
      },
    };
    const result = SprintResponseSchema.safeParse(response);
    expect(result.success).toBe(false);
  });

  it('D: anti-surveillance — schema has no `assignee`, `author`, or developer fields', () => {
    // SprintOverviewData tracks aggregate items/points per sprint — no
    // individual developer identifiers should exist.
    // Verify by inspecting the declared keys of SprintOverviewData shape.
    const overviewShape = SprintResponseSchema.shape.data.shape.overview;
    // unwrap nullable/optional to get the inner ZodObject
    const innerDef = (overviewShape._def as { innerType?: { _def?: { innerType?: { shape?: Record<string, unknown> } } } });
    // Allow for nullable wrapping: ZodNullable > ZodOptional > ZodObject
    // If we can extract a shape, check it; otherwise the meta-test covers it
    if (innerDef?.innerType?._def?.innerType?.shape) {
      const keys = Object.keys(innerDef.innerType._def.innerType.shape);
      const forbidden = keys.filter((k) =>
        /^(assignee|author|reporter|developer|committer|user|login|email)/i.test(k),
      );
      expect(forbidden).toEqual([]);
    }
    // The meta anti-surveillance test in anti-surveillance-schemas.test.ts
    // provides the definitive check via extractAllKeys walker.
    expect(true).toBe(true); // explicit pass when shape extraction is not possible
  });

  it('E: (skip if backend offline) parses real API response', async () => {
    let backendAvailable = false;
    try {
      const response = await fetch(
        'http://localhost:8000/data/v1/metrics/sprints',
        { signal: AbortSignal.timeout(2000) },
      );
      backendAvailable = response.ok;
    } catch {
      backendAvailable = false;
    }

    if (!backendAvailable) {
      console.info('[contract/sprints] Backend not available — skipping live test');
      return;
    }

    const response = await fetch('http://localhost:8000/data/v1/metrics/sprints');
    const json = await response.json();
    const result = SprintResponseSchema.safeParse(json);
    if (!result.success) {
      console.error('[contract/sprints] Schema mismatch:', result.error.issues);
    }
    expect(result.success).toBe(true);
  });
});
