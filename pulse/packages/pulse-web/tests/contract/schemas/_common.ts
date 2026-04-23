/**
 * Shared Zod primitives and the anti-surveillance gate for all metrics
 * contract schemas.
 *
 * DESIGN PRINCIPLES
 * -----------------
 * 1. Schemas here mirror the WIRE FORMAT (snake_case, as Pydantic serialises)
 *    not the camelCase FE types — contract tests are about the HTTP boundary.
 * 2. MetricsEnvelope is extended by every endpoint schema via .extend({}).
 * 3. The anti-surveillance gate is a compile-time / test-time check: if a new
 *    schema inadvertently adds an `assignee` or `author` field it will be
 *    caught here before any PR merges.
 *
 * Parallels the backend gate in:
 *   pulse/packages/pulse-data/tests/contract/test_anti_surveillance_schemas.py
 */

import { z } from 'zod';

// ---------------------------------------------------------------------------
// Common envelope — all /metrics/* endpoints wrap their payload in this shape
// ---------------------------------------------------------------------------

/**
 * The MetricsEnvelope returned by every standard metrics endpoint.
 *
 * Observations:
 * - period_end is always present (string ISO datetime in practice)
 * - period_start is nullable — very old snapshots may lack it
 * - team_id is nullable — null means org-wide (no filter applied)
 * - calculated_at is nullable — absent when the endpoint returns an empty
 *   fallback response (no snapshot found)
 */
export const MetricsEnvelopeSchema = z.object({
  period: z.string(),
  period_start: z.string().nullable(),
  period_end: z.string().nullable(),
  team_id: z.string().nullable(),
  calculated_at: z.string().nullable(),
});

// ---------------------------------------------------------------------------
// Anti-surveillance: forbidden field name patterns
// ---------------------------------------------------------------------------

/**
 * Field name patterns that MUST NOT appear in any metrics contract schema.
 *
 * Rationale: PULSE is anti-surveillance by design. Dashboards surface
 * aggregate team/squad/repo-level signals only. Individual developer
 * identifiers (assignee, author, reporter, etc.) must never leak into
 * the metrics wire format.
 *
 * These patterns mirror the FORBIDDEN_FIELD_PATTERNS list in the Python
 * gate so that both layers enforce the same invariant.
 */
export const FORBIDDEN_FIELD_PATTERNS: RegExp[] = [
  /^assignee$/i,
  /^assignee_[a-z_]+$/i, // assignee_name, assignee_email, assignee_id
  /^author$/i,
  /^author_[a-z_]+$/i,
  /^reporter$/i,
  /^reporter_[a-z_]+$/i,
  /^developer$/i,
  /^developer_[a-z_]+$/i,
  /^committer$/i,
  /^committer_[a-z_]+$/i,
  /^user$/i,
  /^user_[a-z_]+$/i, // user_id, user_email, user_name
  /^login$/i,
  /^email$/i,
  /^[a-z_]+_email$/i, // contact_email, any_email — cautious by default
];

export function isForbiddenFieldName(name: string): boolean {
  return FORBIDDEN_FIELD_PATTERNS.some((pattern) => pattern.test(name));
}

// ---------------------------------------------------------------------------
// Schema key extraction — walks Zod schemas recursively
// ---------------------------------------------------------------------------

/**
 * Extract all field names reachable from a Zod schema, walking into nested
 * ZodObject, ZodArray, ZodOptional, ZodNullable, and ZodDefault shapes.
 *
 * Returns a flat list of field names (keys only, not paths). This is
 * intentionally breadth-first so every level of nesting is inspected.
 *
 * Implementation note: We use `._def` (Zod v3 internals). These are stable
 * public-enough internals — Zod v3 has not changed ._def shapes in any minor
 * release. If Zod v4 changes this, the anti-surveillance tests will fail
 * visibly rather than silently passing (the helper returns [] on unknown
 * typeName, which means no forbidden keys are found — but the companion test
 * `meta-test: helper finds fields in simple object` catches that regression).
 */
export function extractAllKeys(schema: z.ZodTypeAny, visited = new Set<z.ZodTypeAny>()): string[] {
  if (visited.has(schema)) return [];
  visited.add(schema);

  const def = (schema as { _def: { typeName: string; [k: string]: unknown } })._def;

  switch (def.typeName) {
    case 'ZodObject': {
      const shape = (def as { shape: () => Record<string, z.ZodTypeAny> }).shape();
      const keys: string[] = Object.keys(shape);
      for (const child of Object.values(shape)) {
        keys.push(...extractAllKeys(child as z.ZodTypeAny, visited));
      }
      return keys;
    }
    case 'ZodArray':
      return extractAllKeys(
        (def as { type: z.ZodTypeAny }).type,
        visited,
      );
    case 'ZodOptional':
    case 'ZodNullable':
    case 'ZodDefault':
      return extractAllKeys(
        (def as { innerType: z.ZodTypeAny }).innerType,
        visited,
      );
    case 'ZodUnion':
    case 'ZodDiscriminatedUnion': {
      const options = (def as { options: z.ZodTypeAny[] }).options;
      return options.flatMap((o) => extractAllKeys(o, visited));
    }
    case 'ZodIntersection':
      return [
        ...extractAllKeys((def as { left: z.ZodTypeAny }).left, visited),
        ...extractAllKeys((def as { right: z.ZodTypeAny }).right, visited),
      ];
    default:
      return [];
  }
}
