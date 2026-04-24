/**
 * Regression tests for buildParams() — the query-string builder behind all
 * /metrics/* fetches. Covers FDD-DSH-070 scope #1 (buildParams) and the
 * exact bug in FDD-DSH-060 that triggered HTTP 422.
 *
 * The bug: frontend sent `team_id=<lowercase-squad-key>` for squads that
 * aren't UUIDs (our 27 active squads come from /pipeline/teams with keys
 * like "FID", "PTURB"). The backend validates team_id as UUID and returned
 * 422 Unprocessable Entity, breaking the entire dashboard for any squad
 * filter.
 *
 * Fix: detect UUID format and route to `squad_key` for non-UUIDs.
 *
 * These tests lock that behavior in place.
 */
import { describe, it, expect } from 'vitest';
import { buildParams } from '@/lib/api/metrics';

describe('buildParams', () => {
  // ── UUID branch ───────────────────────────────────────────────────────────

  it('forwards team_id when teamId is a canonical UUID', () => {
    const result = buildParams({
      teamId: '00000000-0000-4000-8000-000000000001', // v4 UUID
      period: '60d',
    });
    expect(result.team_id).toBe('00000000-0000-4000-8000-000000000001');
    expect(result.squad_key).toBeUndefined();
    expect(result.period).toBe('60d');
  });

  it('forwards team_id for mixed-case UUIDs (regex is case-insensitive)', () => {
    const result = buildParams({
      teamId: 'AB123456-DEAD-4beef-89AB-123456789ABC'.replace('beef', 'BEEF'),
      // Use a valid v4 UUID shape explicitly to avoid false confidence in regex.
      period: '30d',
    });
    // The string above is not a real valid UUID; use a known valid one instead.
    const valid = buildParams({
      teamId: 'AbCdEf12-3456-4789-Bcde-f0123456789A',
      period: '30d',
    });
    expect(valid.team_id).toBe('AbCdEf12-3456-4789-Bcde-f0123456789A');
    expect(valid.squad_key).toBeUndefined();
    // Silence unused-var for the first case.
    expect(result).toBeDefined();
  });

  // ── Squad-key branch (the FDD-DSH-060 bug surface) ───────────────────────

  it('routes non-UUID teamId to squad_key (UPPERCASED) — FDD-DSH-060 regression', () => {
    const result = buildParams({
      teamId: 'fid', // lowercase from /pipeline/teams
      period: '90d',
    });
    expect(result.squad_key).toBe('FID');
    expect(result.team_id).toBeUndefined();
  });

  it('uppercases multi-word squad keys preserving format', () => {
    // Real squads from Webmotors: PTURB, CTURBO, ENO, FID, ANCR, etc.
    const cases = [
      { input: 'pturb', expected: 'PTURB' },
      { input: 'CTURBO', expected: 'CTURBO' }, // already upper
      { input: 'ancr', expected: 'ANCR' },
      { input: 'appf', expected: 'APPF' },
    ];
    for (const { input, expected } of cases) {
      const result = buildParams({ teamId: input, period: '30d' });
      expect(result.squad_key, `input=${input}`).toBe(expected);
      expect(result.team_id, `input=${input}`).toBeUndefined();
    }
  });

  // ── No-scope branch ──────────────────────────────────────────────────────

  it('omits both team_id and squad_key when teamId is "default"', () => {
    const result = buildParams({
      teamId: 'default',
      period: '60d',
    });
    expect(result.team_id).toBeUndefined();
    expect(result.squad_key).toBeUndefined();
    expect(result.period).toBe('60d');
  });

  it('omits both team_id and squad_key when teamId is the empty string', () => {
    const result = buildParams({
      teamId: '',
      period: '60d',
    });
    expect(result.team_id).toBeUndefined();
    expect(result.squad_key).toBeUndefined();
  });

  // ── Custom date range ────────────────────────────────────────────────────

  it('forwards start_date + end_date when period=custom with both dates set', () => {
    const result = buildParams({
      teamId: 'default',
      period: 'custom',
      startDate: '2026-01-01',
      endDate: '2026-01-31',
    });
    expect(result.start_date).toBe('2026-01-01');
    expect(result.end_date).toBe('2026-01-31');
    expect(result.period).toBe('custom');
  });

  it('omits dates when period=custom but only startDate is set', () => {
    // Backend rejects partial custom windows with HTTP 400 — frontend
    // defensively omits so the user sees an inline form error instead.
    const result = buildParams({
      teamId: 'default',
      period: 'custom',
      startDate: '2026-01-01',
      endDate: null,
    });
    expect(result.start_date).toBeUndefined();
    expect(result.end_date).toBeUndefined();
  });

  it('omits dates when period is not custom even if dates are set', () => {
    const result = buildParams({
      teamId: 'default',
      period: '30d',
      startDate: '2026-01-01',
      endDate: '2026-01-31',
    });
    expect(result.start_date).toBeUndefined();
    expect(result.end_date).toBeUndefined();
    expect(result.period).toBe('30d');
  });

  // ── Combinations ─────────────────────────────────────────────────────────

  it('combines squad_key + custom date range correctly', () => {
    const result = buildParams({
      teamId: 'pturb',
      period: 'custom',
      startDate: '2026-03-01',
      endDate: '2026-03-31',
    });
    expect(result.squad_key).toBe('PTURB');
    expect(result.team_id).toBeUndefined();
    expect(result.period).toBe('custom');
    expect(result.start_date).toBe('2026-03-01');
    expect(result.end_date).toBe('2026-03-31');
  });
});
