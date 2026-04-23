/**
 * Zod schema for GET /data/v1/metrics/flow-health
 *
 * Source of truth: pulse/packages/pulse-data/src/contexts/metrics/schemas.py
 *   AgingWipItem        (individual in-flight work item)
 *   AgingWipSummary     (aggregate stats)
 *   FlowEfficiencyData  (touch time / cycle time ratio)
 *   SquadFlowSummary    (per-squad aggregate)
 *   FlowHealthResponse  (envelope + all of the above)
 *
 * Wire format observations (from routes.py + schemas.py):
 * - Extends MetricsEnvelope (has period, period_start, period_end, etc.)
 * - Additional top-level fields: squad_key, period_days
 * - `aging_wip_items` is an array that MUST NOT contain assignee/author fields
 *   (anti-surveillance contract, explicitly documented in the Pydantic model)
 * - `flow_efficiency.value` is 0..1 (ratio) or null when insufficient data
 * - `squads` is ordered by at_risk_count DESC from the backend
 *
 * ANTI-SURVEILLANCE NOTE:
 *   AgingWipItem intentionally omits assignee, author, reporter, creator.
 *   issue_key is a public artifact (appears in PR titles, commits).
 *   title/description are issue-level fields — may contain PII typed by
 *   humans but are display-only and description is truncated to ~300 chars.
 */

import { z } from 'zod';
import { MetricsEnvelopeSchema } from './_common';

// ---------------------------------------------------------------------------
// AgingWipItem — single in-flight work item (anti-surveillance: no author/assignee)
// ---------------------------------------------------------------------------

const AgingWipItemSchema = z.object({
  issue_key: z.string(),
  title: z.string().nullable().optional(),
  description: z.string().nullable().optional(),
  issue_type: z.string().nullable().optional(),
  age_days: z.number(),
  status: z.string(),
  status_category: z.enum(['in_progress', 'in_review']),
  squad_key: z.string().nullable(),
  squad_name: z.string().nullable(),
  is_at_risk: z.boolean(),
});

// ---------------------------------------------------------------------------
// AgingWipSummary — aggregate stats for the tenant or squad's WIP
// ---------------------------------------------------------------------------

const AgingWipSummarySchema = z.object({
  count: z.number().int(),
  p50_days: z.number().nullable().optional(),
  p85_days: z.number().nullable().optional(),
  at_risk_count: z.number().int(),
  at_risk_threshold_days: z.number().nullable().optional(),
  baseline_source: z.string(),
});

// ---------------------------------------------------------------------------
// FlowEfficiencyData — touch time / cycle time ratio
// ---------------------------------------------------------------------------

const FlowEfficiencyDataSchema = z.object({
  value: z.number().min(0).max(1).nullable(),
  sample_size: z.number().int(),
  formula_version: z.string(),
  formula_disclaimer: z.string(),
  insufficient_data: z.boolean(),
});

// ---------------------------------------------------------------------------
// SquadFlowSummary — per-squad aggregate (ordered by at_risk_count DESC)
// ---------------------------------------------------------------------------

const SquadFlowSummarySchema = z.object({
  squad_key: z.string(),
  squad_name: z.string(),
  wip_count: z.number().int(),
  at_risk_count: z.number().int(),
  risk_pct: z.number().min(0).max(1),
  p50_age_days: z.number().nullable().optional(),
  p85_age_days: z.number().nullable().optional(),
  flow_efficiency: z.number().min(0).max(1).nullable().optional(),
  fe_sample_size: z.number().int(),
  intensity_throughput_30d: z.number().int(),
});

// ---------------------------------------------------------------------------
// FlowHealthResponse — envelope + all sub-models (most complex schema)
// ---------------------------------------------------------------------------

export const FlowHealthResponseSchema = MetricsEnvelopeSchema.extend({
  squad_key: z.string().nullable(),
  period_days: z.number().int(),
  aging_wip: AgingWipSummarySchema,
  aging_wip_items: z.array(AgingWipItemSchema),
  flow_efficiency: FlowEfficiencyDataSchema,
  squads: z.array(SquadFlowSummarySchema),
});

export {
  AgingWipItemSchema,
  AgingWipSummarySchema,
  FlowEfficiencyDataSchema,
  SquadFlowSummarySchema,
};
