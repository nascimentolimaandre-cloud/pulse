/**
 * Zod schema for GET /data/v1/metrics/cycle-time
 *
 * Source of truth: pulse/packages/pulse-data/src/contexts/metrics/schemas.py
 *   CycleTimeBreakdownData  (phase breakdown with percentiles)
 *   CycleTimeMetricsData    (breakdown + trend)
 *   CycleTimeResponse       (envelope + data)
 *
 * Wire format observations (from routes.py + schemas.py):
 * - All percentile fields are float | None — the backend only populates them
 *   when ≥ 1 PR completed in the period
 * - `pr_count` has a default of 0 and is always present as an integer
 * - `bottleneck_phase` is a string like "coding" | "pickup" | "review" |
 *   "deploy" — or null when the bottleneck cannot be determined
 * - `breakdown` itself is nullable — absent when no cycle time data exists
 * - `trend` is list[dict] | None — each dict has {period, p50, p85, p95}
 *   shapes but is untyped at this layer (opaque to FE, used only for charting)
 */

import { z } from 'zod';
import { MetricsEnvelopeSchema } from './_common';

// ---------------------------------------------------------------------------
// CycleTimeBreakdownData — phase breakdown with percentiles
// ---------------------------------------------------------------------------

const CycleTimeBreakdownDataSchema = z.object({
  coding_p50: z.number().nullable().optional(),
  coding_p85: z.number().nullable().optional(),
  coding_p95: z.number().nullable().optional(),
  pickup_p50: z.number().nullable().optional(),
  pickup_p85: z.number().nullable().optional(),
  pickup_p95: z.number().nullable().optional(),
  review_p50: z.number().nullable().optional(),
  review_p85: z.number().nullable().optional(),
  review_p95: z.number().nullable().optional(),
  deploy_p50: z.number().nullable().optional(),
  deploy_p85: z.number().nullable().optional(),
  deploy_p95: z.number().nullable().optional(),
  total_p50: z.number().nullable().optional(),
  total_p85: z.number().nullable().optional(),
  total_p95: z.number().nullable().optional(),
  bottleneck_phase: z.string().nullable().optional(),
  pr_count: z.number().int(),
});

// ---------------------------------------------------------------------------
// CycleTimeMetricsData — breakdown + trend list
// ---------------------------------------------------------------------------

const CycleTimeMetricsDataSchema = z.object({
  breakdown: CycleTimeBreakdownDataSchema.nullable().optional(),
  // trend is an opaque list of dicts — frontend passes it straight to the
  // chart library. We only validate that it is an array or null.
  trend: z.array(z.record(z.unknown())).nullable().optional(),
});

// ---------------------------------------------------------------------------
// CycleTimeResponse — envelope + data (13 breakdown fields visible in data)
// ---------------------------------------------------------------------------

export const CycleTimeResponseSchema = MetricsEnvelopeSchema.extend({
  data: CycleTimeMetricsDataSchema,
});

export { CycleTimeBreakdownDataSchema, CycleTimeMetricsDataSchema };
