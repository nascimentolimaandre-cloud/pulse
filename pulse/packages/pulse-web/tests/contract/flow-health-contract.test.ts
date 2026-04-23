/**
 * Contract tests: GET /data/v1/metrics/flow-health (FlowHealthResponse)
 *
 * Validates that the Zod schema correctly describes the wire contract for the
 * Kanban Flow Health endpoint. Tests use synthetic fixtures.
 *
 * This is the most complex schema: it combines the MetricsEnvelope with
 * AgingWipSummary (aggregate), AgingWipItem[] (item list), FlowEfficiencyData,
 * and SquadFlowSummary[] (per-squad view).
 *
 * ANTI-SURVEILLANCE FOCUS:
 *   AgingWipItem intentionally omits assignee/author. This test specifically
 *   verifies that attempting to inject those fields is handled gracefully.
 *
 * Test plan:
 *   A. Valid well-formed response parses correctly
 *   B. Missing required fields in aging_wip are rejected
 *   C. Type mismatches (age_days as string, is_at_risk as string) are rejected
 *   D. Anti-surveillance: assignee injected into aging_wip_items is stripped
 *   E. (skip if offline) Real API response parses successfully
 */

import { describe, it, expect } from 'vitest';
import { FlowHealthResponseSchema } from './schemas/flow-health.schema';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const VALID_AGING_WIP_ITEM = {
  issue_key: 'OKM-4312',
  title: 'Integrar autenticação SSO com IdP corporativo',
  description: 'Implementar fluxo de login via SAML 2.0...',
  issue_type: 'story',
  age_days: 12.5,
  status: 'Em Desenvolvimento',
  status_category: 'in_progress' as const,
  squad_key: 'OKM',
  squad_name: 'OKM - Checkout & Pagamentos',
  is_at_risk: false,
};

const VALID_AT_RISK_ITEM = {
  issue_key: 'FID-888',
  title: null,
  description: null,
  issue_type: 'bug',
  age_days: 31.0,
  status: 'Em Revisão',
  status_category: 'in_review' as const,
  squad_key: 'FID',
  squad_name: 'FID - Financiamento',
  is_at_risk: true,
};

const VALID_AGING_WIP_SUMMARY = {
  count: 47,
  p50_days: 9.5,
  p85_days: 22.0,
  at_risk_count: 8,
  at_risk_threshold_days: 28.0,
  baseline_source: 'tenant_p85_90d',
};

const VALID_FLOW_EFFICIENCY = {
  value: 0.34,
  sample_size: 63,
  formula_version: 'v1_simplified',
  formula_disclaimer: 'Eficiência de Fluxo v1 (simplificada): touch time / cycle time.',
  insufficient_data: false,
};

const VALID_SQUAD_SUMMARY = {
  squad_key: 'OKM',
  squad_name: 'OKM - Checkout & Pagamentos',
  wip_count: 12,
  at_risk_count: 2,
  risk_pct: 0.167,
  p50_age_days: 8.5,
  p85_age_days: 19.0,
  flow_efficiency: 0.38,
  fe_sample_size: 18,
  intensity_throughput_30d: 24,
};

const VALID_FLOW_HEALTH_RESPONSE = {
  period: '60d',
  period_start: '2026-02-22T00:00:00+00:00',
  period_end: '2026-04-23T00:00:00+00:00',
  team_id: null,
  calculated_at: '2026-04-23T10:00:00+00:00',
  squad_key: null,
  period_days: 60,
  aging_wip: VALID_AGING_WIP_SUMMARY,
  aging_wip_items: [VALID_AGING_WIP_ITEM, VALID_AT_RISK_ITEM],
  flow_efficiency: VALID_FLOW_EFFICIENCY,
  squads: [VALID_SQUAD_SUMMARY],
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('FlowHealthResponse contract (Zod)', () => {
  it('A: validates a well-formed response with all sub-models present', () => {
    const result = FlowHealthResponseSchema.safeParse(VALID_FLOW_HEALTH_RESPONSE);
    expect(result.success).toBe(true);
  });

  it('A2: validates when squad_key is set (squad-filtered request)', () => {
    const response = {
      ...VALID_FLOW_HEALTH_RESPONSE,
      squad_key: 'OKM',
      aging_wip_items: [VALID_AGING_WIP_ITEM],
      squads: [VALID_SQUAD_SUMMARY],
    };
    const result = FlowHealthResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('A3: validates with empty arrays (no active WIP in period)', () => {
    const response = {
      ...VALID_FLOW_HEALTH_RESPONSE,
      aging_wip: { count: 0, p50_days: null, p85_days: null, at_risk_count: 0, at_risk_threshold_days: null, baseline_source: 'absolute_fallback' },
      aging_wip_items: [],
      flow_efficiency: {
        value: null,
        sample_size: 0,
        formula_version: 'v1_simplified',
        formula_disclaimer: '',
        insufficient_data: true,
      },
      squads: [],
    };
    const result = FlowHealthResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('A4: validates status_category as in_review', () => {
    const response = {
      ...VALID_FLOW_HEALTH_RESPONSE,
      aging_wip_items: [{ ...VALID_AGING_WIP_ITEM, status_category: 'in_review' }],
    };
    const result = FlowHealthResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('A5: validates flow_efficiency.value=null when insufficient_data=true', () => {
    const response = {
      ...VALID_FLOW_HEALTH_RESPONSE,
      flow_efficiency: {
        value: null,
        sample_size: 2,
        formula_version: 'v1_simplified',
        formula_disclaimer: 'Dados insuficientes (mínimo 5 issues).',
        insufficient_data: true,
      },
    };
    const result = FlowHealthResponseSchema.safeParse(response);
    expect(result.success).toBe(true);
  });

  it('B: rejects response missing the required `aging_wip` field', () => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { aging_wip: _removed, ...withoutAgingWip } = VALID_FLOW_HEALTH_RESPONSE;
    const result = FlowHealthResponseSchema.safeParse(withoutAgingWip);
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p.includes('aging_wip'))).toBe(true);
    }
  });

  it('B2: rejects response missing required `flow_efficiency` field', () => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { flow_efficiency: _removed, ...withoutFE } = VALID_FLOW_HEALTH_RESPONSE;
    const result = FlowHealthResponseSchema.safeParse(withoutFE);
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p.includes('flow_efficiency'))).toBe(true);
    }
  });

  it('C: rejects age_days as string instead of number', () => {
    const response = {
      ...VALID_FLOW_HEALTH_RESPONSE,
      aging_wip_items: [
        { ...VALID_AGING_WIP_ITEM, age_days: 'twelve-and-a-half' }, // wrong type
      ],
    };
    const result = FlowHealthResponseSchema.safeParse(response);
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p.includes('age_days'))).toBe(true);
    }
  });

  it('C2: rejects is_at_risk as string instead of boolean', () => {
    const response = {
      ...VALID_FLOW_HEALTH_RESPONSE,
      aging_wip_items: [
        { ...VALID_AGING_WIP_ITEM, is_at_risk: 'yes' }, // wrong type
      ],
    };
    const result = FlowHealthResponseSchema.safeParse(response);
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p.includes('is_at_risk'))).toBe(true);
    }
  });

  it('C3: rejects invalid status_category enum value', () => {
    const response = {
      ...VALID_FLOW_HEALTH_RESPONSE,
      aging_wip_items: [
        { ...VALID_AGING_WIP_ITEM, status_category: 'done' }, // invalid — not in enum
      ],
    };
    const result = FlowHealthResponseSchema.safeParse(response);
    expect(result.success).toBe(false);
    if (!result.success) {
      const paths = result.error.issues.map((i) => i.path.join('.'));
      expect(paths.some((p) => p.includes('status_category'))).toBe(true);
    }
  });

  it('C4: rejects flow_efficiency.value outside 0..1 range', () => {
    const response = {
      ...VALID_FLOW_HEALTH_RESPONSE,
      flow_efficiency: {
        ...VALID_FLOW_EFFICIENCY,
        value: 1.5, // invalid — must be 0..1
      },
    };
    const result = FlowHealthResponseSchema.safeParse(response);
    expect(result.success).toBe(false);
  });

  it('D: anti-surveillance — `assignee` injected into aging_wip_items is stripped', () => {
    // AgingWipItem uses ZodObject default strip mode — unknown keys are
    // removed. This is the core anti-surveillance guarantee at the schema level.
    const responseWithAssignee = {
      ...VALID_FLOW_HEALTH_RESPONSE,
      aging_wip_items: [
        {
          ...VALID_AGING_WIP_ITEM,
          assignee: 'developer@webmotors.com.br', // MUST be stripped
          author: 'committer@webmotors.com.br',   // MUST be stripped
        },
      ],
    };
    const result = FlowHealthResponseSchema.safeParse(responseWithAssignee);
    expect(result.success).toBe(true);
    if (result.success) {
      const itemKeys = Object.keys(result.data.aging_wip_items[0]);
      expect(itemKeys).not.toContain('assignee');
      expect(itemKeys).not.toContain('author');
    }
  });

  it('D2: anti-surveillance — `author` injected into squads is stripped', () => {
    const responseWithAuthor = {
      ...VALID_FLOW_HEALTH_RESPONSE,
      squads: [
        {
          ...VALID_SQUAD_SUMMARY,
          author: 'team-lead@webmotors.com.br', // MUST be stripped
        },
      ],
    };
    const result = FlowHealthResponseSchema.safeParse(responseWithAuthor);
    expect(result.success).toBe(true);
    if (result.success) {
      const squadKeys = Object.keys(result.data.squads[0]);
      expect(squadKeys).not.toContain('author');
    }
  });

  it('E: (skip if backend offline) parses real API response', async () => {
    let backendAvailable = false;
    try {
      const response = await fetch(
        'http://localhost:8000/data/v1/metrics/flow-health?period=60d',
        { signal: AbortSignal.timeout(2000) },
      );
      backendAvailable = response.ok;
    } catch {
      backendAvailable = false;
    }

    if (!backendAvailable) {
      console.info('[contract/flow-health] Backend not available — skipping live test');
      return;
    }

    const response = await fetch('http://localhost:8000/data/v1/metrics/flow-health?period=60d');
    const json = await response.json();
    const result = FlowHealthResponseSchema.safeParse(json);
    if (!result.success) {
      console.error('[contract/flow-health] Schema mismatch:', result.error.issues);
    }
    expect(result.success).toBe(true);
  });
});
