/**
 * Zod schema for GET /data/v1/metrics/throughput
 *
 * Source of truth: pulse/packages/pulse-data/src/contexts/metrics/schemas.py
 *   ThroughputMetricsData  (trend list + pr_analytics dict)
 *   ThroughputResponse     (envelope + data)
 *
 * Wire format observations (from routes.py + schemas.py):
 * - `trend` is list[dict] | None — snapshot worker stores points as
 *   {"points": [...]} wrapper; routes.py unwraps to the list before returning
 * - `pr_analytics` is dict[str, Any] | None — opaque analytics blob.
 *   Current keys observed from the worker: total_merged, avg_cycle_time_hours,
 *   avg_pr_size, size_distribution. Not typed here because this is a
 *   free-form analytics blob and the FE reads it via a transformer.
 *
 * FIELD DIVERGENCE NOTE:
 *   The TypeScript ThroughputResponse in src/types/metrics.ts is a
 *   client-side TRANSFORMED shape (weeklyData, averageMergedPerWeek, etc.)
 *   NOT the wire format. The wire format has `data.trend` (raw list) and
 *   `data.pr_analytics` (raw dict). This schema correctly mirrors the wire.
 */

import { z } from 'zod';
import { MetricsEnvelopeSchema } from './_common';

// ---------------------------------------------------------------------------
// ThroughputMetricsData — opaque lists/dicts; frontend transforms them
// ---------------------------------------------------------------------------

const ThroughputMetricsDataSchema = z.object({
  // trend: [{period, count, ...}, ...] — opaque, passed to chart library
  trend: z.array(z.record(z.unknown())).nullable().optional(),
  // pr_analytics: {total_merged, avg_cycle_time_hours, ...} — opaque analytics
  pr_analytics: z.record(z.unknown()).nullable().optional(),
});

// ---------------------------------------------------------------------------
// ThroughputResponse — envelope + data
// ---------------------------------------------------------------------------

export const ThroughputResponseSchema = MetricsEnvelopeSchema.extend({
  data: ThroughputMetricsDataSchema,
});

export { ThroughputMetricsDataSchema };
