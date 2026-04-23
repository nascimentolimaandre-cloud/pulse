/**
 * Zod schema for GET /data/v1/metrics/sprints
 *
 * Source of truth: pulse/packages/pulse-data/src/contexts/metrics/schemas.py
 *   SprintOverviewData    (latest sprint summary)
 *   SprintComparisonData  (multi-sprint velocity comparison)
 *   SprintMetricsData     (overview + comparison)
 *   SprintResponse        (NOT an envelope — different from all other endpoints)
 *
 * IMPORTANT STRUCTURAL DIVERGENCE:
 *   SprintResponse does NOT extend MetricsEnvelope. It is defined directly
 *   as `class SprintResponse(BaseModel)` with only:
 *     - team_id: UUID | None
 *     - calculated_at: datetime | None
 *     - data: SprintMetricsData
 *   This is different from all other /metrics/* endpoints which have period,
 *   period_start, period_end fields. Sprints are not period-windowed —
 *   they are keyed by sprint ID.
 *
 * Wire format observations (from routes.py + schemas.py):
 * - `overview` is nullable — absent when no sprint snapshots exist
 * - `comparison.sprints` is list[dict] — opaque per-sprint objects
 * - `velocity_trend` defaults to "insufficient_data"
 * - Integer fields in SprintOverviewData have defaults (0) — always present
 */

import { z } from 'zod';

// ---------------------------------------------------------------------------
// SprintOverviewData — latest sprint summary (15 fields)
// ---------------------------------------------------------------------------

const SprintOverviewDataSchema = z.object({
  committed_items: z.number().int(),
  added_items: z.number().int(),
  removed_items: z.number().int(),
  completed_items: z.number().int(),
  carried_over_items: z.number().int(),
  final_scope_items: z.number().int(),
  completion_rate: z.number().nullable().optional(),
  scope_creep_pct: z.number().nullable().optional(),
  carryover_rate: z.number().nullable().optional(),
  committed_points: z.number(),
  completed_points: z.number(),
  completion_rate_points: z.number().nullable().optional(),
  sprint_name: z.string().nullable().optional(),
  started_at: z.string().nullable().optional(),
  completed_at: z.string().nullable().optional(),
});

// ---------------------------------------------------------------------------
// SprintComparisonData — multi-sprint velocity comparison
// ---------------------------------------------------------------------------

const SprintComparisonDataSchema = z.object({
  sprints: z.array(z.record(z.unknown())),
  avg_velocity: z.number().nullable().optional(),
  velocity_trend: z.string(),
});

// ---------------------------------------------------------------------------
// SprintMetricsData — overview + comparison wrapper
// ---------------------------------------------------------------------------

const SprintMetricsDataSchema = z.object({
  overview: SprintOverviewDataSchema.nullable().optional(),
  comparison: SprintComparisonDataSchema.nullable().optional(),
});

// ---------------------------------------------------------------------------
// SprintResponse — NOTE: no period/period_start/period_end (not an envelope)
// ---------------------------------------------------------------------------

export const SprintResponseSchema = z.object({
  team_id: z.string().nullable().optional(),
  calculated_at: z.string().nullable().optional(),
  data: SprintMetricsDataSchema,
});

export { SprintOverviewDataSchema, SprintComparisonDataSchema, SprintMetricsDataSchema };
