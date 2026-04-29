/**
 * Zod schema for GET /data/v1/pipeline/jobs (FDD-OPS-015).
 *
 * Source of truth: pulse/packages/pulse-data/src/contexts/pipeline/schemas.py
 *   ProgressJob (camelCase via _CamelModel)
 *
 * Wire-format notes:
 *   - All optional fields use nullable() (matching `int | None` in Pydantic)
 *   - `progressPct` is computed by the backend (0-100) when itemsEstimate
 *     is set, else null
 *   - `isStalled` is computed: status='running' AND lastProgressAt > 60s ago
 *   - Anti-surveillance: schema MUST NOT contain author/assignee/reporter
 */

import { z } from 'zod';

export const ProgressJobStatusSchema = z.enum([
  'running',
  'done',
  'failed',
  'paused',
  'cancelled',
]);

export const ProgressJobPhaseSchema = z.enum([
  'pre_flight',
  'fetching',
  'normalizing',
  'persisting',
  'done',
  'failed',
]);

export const ProgressJobSchema = z.object({
  scopeKey: z.string(),
  entityType: z.string(),
  phase: ProgressJobPhaseSchema,
  status: ProgressJobStatusSchema,
  itemsDone: z.number().int().nonnegative(),
  itemsEstimate: z.number().int().nonnegative().nullable(),
  progressPct: z.number().min(0).max(100).nullable(),
  itemsPerSecond: z.number().nonnegative(),
  etaSeconds: z.number().int().nonnegative().nullable(),
  startedAt: z.string(),
  lastProgressAt: z.string(),
  finishedAt: z.string().nullable(),
  isStalled: z.boolean(),
  lastError: z.string().nullable(),
});

export const PipelineJobsResponseSchema = z.array(ProgressJobSchema);

export type ProgressJobShape = z.infer<typeof ProgressJobSchema>;
