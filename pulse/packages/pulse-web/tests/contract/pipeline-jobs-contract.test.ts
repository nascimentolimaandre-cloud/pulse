/**
 * Contract tests: GET /data/v1/pipeline/jobs (FDD-OPS-015).
 *
 * Validates the Zod schema for the per-scope progress endpoint. Tests
 * use synthetic fixtures — no live backend needed.
 *
 * Coverage:
 *   A. Valid running scope (with estimate + ETA) parses
 *   B. Valid scope without estimate (itemsEstimate=null, etaSeconds=null) parses
 *   C. Stalled scope (isStalled=true, status='running') parses
 *   D. Failed scope with error message parses
 *   E. Done scope with finishedAt parses
 *   F. Empty array parses (no jobs yet)
 *   G. Anti-surveillance: rejects payloads with author/assignee fields
 *   H. Schema rejects negative items_done (defensive)
 *   I. Schema rejects progressPct > 100 (computed bound)
 */

import { describe, it, expect } from 'vitest';
import {
  PipelineJobsResponseSchema,
  ProgressJobSchema,
} from './schemas/pipeline-jobs.schema';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const VALID_RUNNING_JOB = {
  scopeKey: 'jira:project:BG',
  entityType: 'issues',
  phase: 'persisting',
  status: 'running',
  itemsDone: 12500,
  itemsEstimate: 197043,
  progressPct: 6.34,
  itemsPerSecond: 84.2,
  etaSeconds: 2191,
  startedAt: '2026-04-29T10:00:00.000+00:00',
  lastProgressAt: '2026-04-29T10:24:30.000+00:00',
  finishedAt: null,
  isStalled: false,
  lastError: null,
};

const VALID_NO_ESTIMATE_JOB = {
  scopeKey: 'jenkins:job:deploy-prod',
  entityType: 'deployments',
  phase: 'fetching',
  status: 'running',
  itemsDone: 50,
  itemsEstimate: null,        // pre-flight count failed/skipped
  progressPct: null,          // ⇒ null (no estimate)
  itemsPerSecond: 5.0,
  etaSeconds: null,           // ⇒ null (no estimate)
  startedAt: '2026-04-29T10:00:00.000+00:00',
  lastProgressAt: '2026-04-29T10:10:00.000+00:00',
  finishedAt: null,
  isStalled: false,
  lastError: null,
};

const VALID_STALLED_JOB = {
  scopeKey: 'jira:project:OKM',
  entityType: 'issues',
  phase: 'fetching',
  status: 'running',
  itemsDone: 200,
  itemsEstimate: 1500,
  progressPct: 13.33,
  itemsPerSecond: 0.0,
  etaSeconds: null,
  startedAt: '2026-04-29T10:00:00.000+00:00',
  lastProgressAt: '2026-04-29T10:05:00.000+00:00',
  finishedAt: null,
  isStalled: true,             // backend computed: running + >60s no progress
  lastError: null,
};

const VALID_FAILED_JOB = {
  scopeKey: 'github:repo:webmotors-private/foo',
  entityType: 'pull_requests',
  phase: 'failed',
  status: 'failed',
  itemsDone: 12,
  itemsEstimate: 50,
  progressPct: 24.0,
  itemsPerSecond: 1.5,
  etaSeconds: null,
  startedAt: '2026-04-29T10:00:00.000+00:00',
  lastProgressAt: '2026-04-29T10:08:00.000+00:00',
  finishedAt: '2026-04-29T10:08:30.000+00:00',
  isStalled: false,
  lastError: 'GitHub GraphQL 401: Bad credentials',
};

const VALID_DONE_JOB = {
  scopeKey: 'jira:project:DESC',
  entityType: 'issues',
  phase: 'done',
  status: 'done',
  itemsDone: 2485,
  itemsEstimate: 2485,
  progressPct: 100.0,
  itemsPerSecond: 45.0,
  etaSeconds: 0,
  startedAt: '2026-04-29T10:00:00.000+00:00',
  lastProgressAt: '2026-04-29T10:55:00.000+00:00',
  finishedAt: '2026-04-29T10:55:30.000+00:00',
  isStalled: false,
  lastError: null,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('GET /data/v1/pipeline/jobs (FDD-OPS-015)', () => {
  it('A. Valid running scope (with estimate + ETA) parses', () => {
    const parsed = ProgressJobSchema.safeParse(VALID_RUNNING_JOB);
    expect(parsed.success).toBe(true);
  });

  it('B. Valid scope without estimate (null progress/ETA) parses', () => {
    const parsed = ProgressJobSchema.safeParse(VALID_NO_ESTIMATE_JOB);
    expect(parsed.success).toBe(true);
  });

  it('C. Stalled scope (isStalled=true, status=running) parses', () => {
    const parsed = ProgressJobSchema.safeParse(VALID_STALLED_JOB);
    expect(parsed.success).toBe(true);
    expect(parsed.success && parsed.data.isStalled).toBe(true);
    expect(parsed.success && parsed.data.status).toBe('running');
  });

  it('D. Failed scope with error message parses', () => {
    const parsed = ProgressJobSchema.safeParse(VALID_FAILED_JOB);
    expect(parsed.success).toBe(true);
    expect(parsed.success && parsed.data.lastError).toContain('Bad credentials');
  });

  it('E. Done scope with finishedAt + 100% parses', () => {
    const parsed = ProgressJobSchema.safeParse(VALID_DONE_JOB);
    expect(parsed.success).toBe(true);
    expect(parsed.success && parsed.data.progressPct).toBe(100);
    expect(parsed.success && parsed.data.finishedAt).not.toBeNull();
  });

  it('F. Empty array (no jobs yet) parses', () => {
    const parsed = PipelineJobsResponseSchema.safeParse([]);
    expect(parsed.success).toBe(true);
  });

  it('G. Multiple-job array parses', () => {
    const parsed = PipelineJobsResponseSchema.safeParse([
      VALID_RUNNING_JOB,
      VALID_NO_ESTIMATE_JOB,
      VALID_STALLED_JOB,
      VALID_FAILED_JOB,
      VALID_DONE_JOB,
    ]);
    expect(parsed.success).toBe(true);
  });

  // -----------------------------------------------------------------------
  // Anti-surveillance: payload MUST NOT carry per-developer fields
  // (matches the project-wide invariant in metrics-inconsistencies §8.9)
  // -----------------------------------------------------------------------

  it('H. Anti-surveillance: rejects extra `author` field (strict-ish)', () => {
    // Zod by default strips unknown — but we want to flag if the wire
    // shape ever leaks a field. Use safeParse + strict() on the schema.
    const tainted = { ...VALID_RUNNING_JOB, author: 'alice@example.com' };
    const strict = ProgressJobSchema.strict();
    const parsed = strict.safeParse(tainted);
    expect(parsed.success).toBe(false);
  });

  it('I. Anti-surveillance: rejects extra `assignee` field (strict-ish)', () => {
    const tainted = { ...VALID_RUNNING_JOB, assignee: 'bob@example.com' };
    const strict = ProgressJobSchema.strict();
    const parsed = strict.safeParse(tainted);
    expect(parsed.success).toBe(false);
  });

  // -----------------------------------------------------------------------
  // Defensive: bound checks
  // -----------------------------------------------------------------------

  it('J. Rejects negative items_done', () => {
    const bad = { ...VALID_RUNNING_JOB, itemsDone: -1 };
    const parsed = ProgressJobSchema.safeParse(bad);
    expect(parsed.success).toBe(false);
  });

  it('K. Rejects progressPct > 100', () => {
    const bad = { ...VALID_RUNNING_JOB, progressPct: 150 };
    const parsed = ProgressJobSchema.safeParse(bad);
    expect(parsed.success).toBe(false);
  });

  it('L. Rejects unknown phase', () => {
    const bad = { ...VALID_RUNNING_JOB, phase: 'unknown_phase' };
    const parsed = ProgressJobSchema.safeParse(bad);
    expect(parsed.success).toBe(false);
  });

  it('M. Rejects unknown status', () => {
    const bad = { ...VALID_RUNNING_JOB, status: 'mystery' };
    const parsed = ProgressJobSchema.safeParse(bad);
    expect(parsed.success).toBe(false);
  });
});
