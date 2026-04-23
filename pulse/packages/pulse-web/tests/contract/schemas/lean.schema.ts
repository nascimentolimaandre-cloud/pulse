/**
 * Zod schema for GET /data/v1/metrics/lean
 *
 * Source of truth: pulse/packages/pulse-data/src/contexts/metrics/schemas.py
 *   LeanMetricsData  (cfd, wip, lead_time_distribution, throughput, scatterplot)
 *   LeanResponse     (envelope + data)
 *
 * Wire format observations (from routes.py + schemas.py):
 * - `cfd` is list[dict] | None — points from the CFD snapshot, each dict
 *   has {date, todo, in_progress, done, ...} structure (opaque to schema)
 * - `wip` is int | None — current WIP count extracted from snapshot value
 * - `lead_time_distribution` is dict | None — opaque analytics blob with
 *   percentile arrays and histogram bins
 * - `throughput` is list[dict] | None — weekly throughput data points
 * - `scatterplot` is dict | None — {points: [{id, lead_time_days, ...}]}
 *
 * FIELD DIVERGENCE NOTE:
 *   The TypeScript LeanMetrics in src/types/metrics.ts is a transformed shape
 *   with camelCase keys (wipCount, cfdData, scatterplotData). This schema
 *   mirrors the snake_case wire format.
 */

import { z } from 'zod';
import { MetricsEnvelopeSchema } from './_common';

// ---------------------------------------------------------------------------
// LeanMetricsData — all sub-metrics are opaque lists/dicts or a scalar int
// ---------------------------------------------------------------------------

const LeanMetricsDataSchema = z.object({
  // CFD time-series: [{date, backlog, todo, in_progress, review, done}, ...]
  cfd: z.array(z.record(z.unknown())).nullable().optional(),
  // Current WIP item count — integer scalar
  wip: z.number().int().nullable().optional(),
  // Lead time distribution: {p50, p85, p95, histogram: [...]}
  lead_time_distribution: z.record(z.unknown()).nullable().optional(),
  // Weekly throughput points (opaque — same structure as throughput.trend)
  throughput: z.array(z.record(z.unknown())).nullable().optional(),
  // Scatterplot blob: {points: [...], p50, p85, p95}
  scatterplot: z.record(z.unknown()).nullable().optional(),
});

// ---------------------------------------------------------------------------
// LeanResponse — envelope + data (5 payload fields)
// ---------------------------------------------------------------------------

export const LeanResponseSchema = MetricsEnvelopeSchema.extend({
  data: LeanMetricsDataSchema,
});

export { LeanMetricsDataSchema };
