/**
 * Zod schema for GET /data/v1/metrics/dora
 *
 * Source of truth: pulse/packages/pulse-data/src/contexts/metrics/schemas.py
 *   DoraMetricsData  (data payload)
 *   DoraClassifications  (nested classifications object)
 *   DoraResponse  (envelope + data)
 *
 * Wire format observations (from routes.py + schemas.py):
 * - All numeric fields are float | None → z.number().nullable()
 * - `overall_level` is a free string (elite/high/medium/low) — not an enum
 *   because older snapshots may lack it or use unexpected strings
 * - `classifications` is a nested optional object; all of its fields are
 *   optional strings
 *
 * DESIGN NOTE — field divergence found:
 *   The task spec listed `lead_time_for_changes_hours_strict`,
 *   `lead_time_strict_eligible_count`, `lead_time_strict_total_count`,
 *   `df_level`, `lt_level`, `lt_strict_level`, `cfr_level`, `mttr_level`
 *   as fields of DoraResponse. These fields are NOT in DoraMetricsData.
 *   They live inside the raw snapshot `value` dict and are only surfaced by
 *   the /metrics/home endpoint (which constructs HomeMetricCard objects).
 *   The /metrics/dora endpoint returns DoraMetricsData which has
 *   `deployment_frequency_per_day`, `deployment_frequency_per_week`,
 *   `lead_time_for_changes_hours`, `change_failure_rate`,
 *   `mean_time_to_recovery_hours`, `overall_level`, `classifications`.
 *   The task spec was describing the snapshot JSONB shape, not the API shape.
 *   This schema correctly mirrors the actual API contract.
 */

import { z } from 'zod';
import { MetricsEnvelopeSchema } from './_common';

// ---------------------------------------------------------------------------
// DoraClassifications — nested object with per-metric levels
// ---------------------------------------------------------------------------

const DoraClassificationsSchema = z.object({
  deployment_frequency: z.string().nullable().optional(),
  lead_time: z.string().nullable().optional(),
  change_failure_rate: z.string().nullable().optional(),
  mttr: z.string().nullable().optional(),
});

// ---------------------------------------------------------------------------
// DoraMetricsData — the actual DORA metric values
// ---------------------------------------------------------------------------

const DoraMetricsDataSchema = z.object({
  deployment_frequency_per_day: z.number().nullable().optional(),
  deployment_frequency_per_week: z.number().nullable().optional(),
  lead_time_for_changes_hours: z.number().nullable().optional(),
  change_failure_rate: z.number().nullable().optional(),
  mean_time_to_recovery_hours: z.number().nullable().optional(),
  overall_level: z.string().nullable().optional(),
  classifications: DoraClassificationsSchema.nullable().optional(),
});

// ---------------------------------------------------------------------------
// DoraResponse — envelope + data (6 fields total: 5 envelope + 1 data)
// ---------------------------------------------------------------------------

export const DoraResponseSchema = MetricsEnvelopeSchema.extend({
  data: DoraMetricsDataSchema,
});

// Export sub-schemas for reuse in tests
export { DoraMetricsDataSchema, DoraClassificationsSchema };
