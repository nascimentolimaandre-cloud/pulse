/**
 * Contract tests: GET /data/v1/metrics/dora (DoraResponse)
 *
 * Validates that the Zod schema correctly describes the wire contract for the
 * DORA metrics endpoint. Tests use synthetic fixtures — no live backend needed.
 *
 * Test plan:
 *   A. Valid well-formed response parses without error
 *   B. Missing required `data` field is rejected
 *   C. Type mismatch (string where number expected) is rejected
 *   D. Anti-surveillance: injecting `assignee` field is not accepted
 *   E. (skip if offline) Real API response parses successfully
 */

import { describe, it, expect } from 'vitest';
import { DoraResponseSchema } from './schemas/dora.schema';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const VALID_DORA_RESPONSE = {
  period: '30d',
  period_start: '2026-03-24T00:00:00+00:00',
  period_end: '2026-04-23T00:00:00+00:00',
  team_id: null,
  calculated_at: '2026-04-23T10:00:00+00:00',
  data: {
    deployment_frequency_per_day: 2.4,
    deployment_frequency_per_week: 16.8,
    lead_time_for_changes_hours: 36.5,
    change_failure_rate: 0.05,
    mean_time_to_recovery_hours: null,
    overall_level: 'high',
    classifications: {
      deployment_frequency: 'high',
      lead_time: 'high',
      change_failure_rate: 'elite',
      mttr: null,
    },
  },
};

const EMPTY_DATA_DORA_RESPONSE = {
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

describe('DoraResponse contract (Zod)', () => {
  it('A: validates a well-formed response with all fields present', () => {
    const result = DoraResponseSchema.safeParse(VALID_DORA_RESPONSE);
    expect(result.success).toBe(true);
  });

  it('A2: validates empty data object (no snapshots yet — backend fallback path)', () => {
    const result = DoraResponseSchema.safeParse(EMPTY_DATA_DORA_RESPONSE);
    expect(result.success).toBe(true);
  });

  it('A3: validates when classifications is null (pre-classification snapshot)', () => {
    const response = {
      ...VALID_DORA_RESPONSE,
      data: {
        ...VALID_DORA_RESPONSE.data,
        classifications: null,
      },
    };
    const result = DoraResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('A4: validates when all numeric fields are null (partial data)', () => {
    const response = {
      ...VALID_DORA_RESPONSE,
      data: {
        deployment_frequency_per_day: null,
        deployment_frequency_per_week: null,
        lead_time_for_changes_hours: null,
        change_failure_rate: null,
        mean_time_to_recovery_hours: null,
        overall_level: null,
        classifications: null,
      },
    };
    const result = DoraResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('B: rejects response missing the required `data` field', () => {
     
    const { data: _removed, ...withoutData } = VALID_DORA_RESPONSE;
    const result = DoraResponseSchema.safeParse(withoutData);
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p === 'data')).toBe(true);
    }
  });

  it('C: rejects deployment_frequency_per_day as string instead of number', () => {
    const response = {
      ...VALID_DORA_RESPONSE,
      data: {
        ...VALID_DORA_RESPONSE.data,
        deployment_frequency_per_day: 'two-point-four', // wrong type
      },
    };
    const result = DoraResponseSchema.safeParse(response);
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p.includes('deployment_frequency_per_day'))).toBe(true);
    }
  });

  it('C2: rejects change_failure_rate as boolean instead of number', () => {
    const response = {
      ...VALID_DORA_RESPONSE,
      data: {
        ...VALID_DORA_RESPONSE.data,
        change_failure_rate: true, // wrong type
      },
    };
    const result = DoraResponseSchema.safeParse(response);
    expect(result.success).toBe(false);
  });

  it('D: anti-surveillance — Zod strips extra fields (assignee injected into data)', () => {
    // Zod ZodObject by default strips unknown keys (.strip is the default mode).
    // The parsed result should succeed BUT the `assignee` field must not be
    // present in the output (i.e. it is not accepted into the schema shape).
    const responseWithAssignee = {
      ...VALID_DORA_RESPONSE,
      data: {
        ...VALID_DORA_RESPONSE.data,
        assignee: 'john.doe@webmotors.com.br', // must be stripped
      },
    };
    const result = DoraResponseSchema.safeParse(responseWithAssignee);
    // Strip mode: parse succeeds but forbidden key is absent in output
    expect(result.success).toBe(true);
    if (result.success) {
      // The parsed data object must NOT contain `assignee`
      expect(Object.keys(result.data.data)).not.toContain('assignee');
    }
  });

  it('D2: anti-surveillance — `author` injected into classifications is stripped', () => {
    const responseWithAuthor = {
      ...VALID_DORA_RESPONSE,
      data: {
        ...VALID_DORA_RESPONSE.data,
        classifications: {
          ...VALID_DORA_RESPONSE.data.classifications,
          author: 'user-123', // must be stripped
        },
      },
    };
    const result = DoraResponseSchema.safeParse(responseWithAuthor);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(Object.keys(result.data.data.classifications ?? {})).not.toContain('author');
    }
  });

  it('E: (skip if backend offline) parses real API response', async () => {
    let backendAvailable = false;
    try {
      const response = await fetch(
        'http://localhost:8000/data/v1/metrics/dora?period=30d',
        { signal: AbortSignal.timeout(2000) },
      );
      backendAvailable = response.ok;
    } catch {
      backendAvailable = false;
    }

    if (!backendAvailable) {
      console.info('[contract/dora] Backend not available — skipping live test');
      return;
    }

    const response = await fetch('http://localhost:8000/data/v1/metrics/dora?period=30d');
    const json = await response.json();
    const result = DoraResponseSchema.safeParse(json);
    if (!result.success) {
      console.error('[contract/dora] Schema mismatch:', result.error.issues);
    }
    expect(result.success).toBe(true);
  });
});
