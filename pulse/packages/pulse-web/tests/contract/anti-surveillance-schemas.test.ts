/**
 * Anti-surveillance meta-test (QW-5, TypeScript layer)
 *
 * Guarantees that no Zod contract schema for any metrics endpoint exposes
 * individual-author fields (assignee, author, reporter, committer, email, etc.).
 *
 * PULSE is anti-surveillance by design: dashboards surface aggregate
 * team/squad/repo-level signals only. Individual developer data must never
 * leak into metrics wire formats.
 *
 * This test inspects every Zod schema declared in tests/contract/schemas/
 * and walks the schema tree recursively using extractAllKeys(). If any
 * declared field name matches a forbidden pattern, the test fails and
 * blocks the PR.
 *
 * Parallels the backend gate in:
 *   pulse/packages/pulse-data/tests/contract/test_anti_surveillance_schemas.py
 *
 * WHY BOTH LAYERS?
 *   Backend gate: checks Pydantic schemas (source of truth for the wire).
 *   Frontend gate: checks Zod schemas (validates what the FE expects to receive).
 *   Having both means a drift in either layer is caught independently, and the
 *   FE gate catches copy-paste errors when adding new endpoints.
 *
 * ALLOWED EXCEPTIONS:
 *   - `issue_key` — public artifact (appears in PR titles, commits), not PII
 *   - `title`, `description` — issue-level, display-only, truncated at API boundary
 *   - `squad_key`, `squad_name`, `team_id` — team/aggregate level, not individual
 *
 * The explicit allowlist below documents any legitimate use that superficially
 * matches a pattern. Empty by default.
 */

import { describe, it, expect } from 'vitest';
import { z } from 'zod';
import { FORBIDDEN_FIELD_PATTERNS, extractAllKeys, isForbiddenFieldName } from './schemas/_common';
import { DoraResponseSchema } from './schemas/dora.schema';
import { CycleTimeResponseSchema } from './schemas/cycle-time.schema';
import { ThroughputResponseSchema } from './schemas/throughput.schema';
import { LeanResponseSchema } from './schemas/lean.schema';
import { SprintResponseSchema } from './schemas/sprints.schema';
import { FlowHealthResponseSchema } from './schemas/flow-health.schema';

// ---------------------------------------------------------------------------
// Registry: all schemas to inspect
// ---------------------------------------------------------------------------

const SCHEMA_REGISTRY: Array<{ name: string; schema: z.ZodTypeAny }> = [
  { name: 'DoraResponse', schema: DoraResponseSchema },
  { name: 'CycleTimeResponse', schema: CycleTimeResponseSchema },
  { name: 'ThroughputResponse', schema: ThroughputResponseSchema },
  { name: 'LeanResponse', schema: LeanResponseSchema },
  { name: 'SprintResponse', schema: SprintResponseSchema },
  { name: 'FlowHealthResponse', schema: FlowHealthResponseSchema },
];

// ---------------------------------------------------------------------------
// Allowlist: legitimate exceptions (must include rationale comment)
// ---------------------------------------------------------------------------

// Fields that match a forbidden pattern but are acceptable in context.
// Format: `${schemaName}.${fieldName}` — both parts must match.
const EXPLICIT_ALLOWLIST = new Set<string>([
  // No exceptions currently. Add with rationale if needed:
  // e.g. "FlowHealthResponse.creator_id" — if creator_id were a project-level
  // field with no PII (hypothetical), it would be documented here.
]);

// ---------------------------------------------------------------------------
// Meta-tests: validate the test infrastructure itself
// ---------------------------------------------------------------------------

describe('Anti-surveillance: meta-test infrastructure', () => {
  it('FORBIDDEN_FIELD_PATTERNS correctly blocks known bad field names', () => {
    const mustBlock = [
      'assignee',
      'assignee_name',
      'assignee_email',
      'assignee_id',
      'author',
      'author_name',
      'reporter',
      'reporter_id',
      'developer',
      'developer_name',
      'committer',
      'committer_email',
      'user',
      'user_id',
      'user_email',
      'user_name',
      'login',
      'email',
      'contact_email',
      'user_login',
    ];

    for (const name of mustBlock) {
      expect(
        isForbiddenFieldName(name),
        `Pattern should block '${name}' but did not`,
      ).toBe(true);
    }
  });

  it('FORBIDDEN_FIELD_PATTERNS correctly allows legitimate aggregate field names', () => {
    const mustAllow = [
      'squad_key',
      'squad_name',
      'team_id',
      'project_key',
      'repo',
      'issue_key',
      'title',
      'description',
      'status',
      'age_days',
      'wip_count',
      'lead_time_hours',
      'deployment_frequency_per_day',
      'covered',
      'at_risk_count',
      'risk_pct',
      'flow_efficiency',
      'pr_count',
      'sample_size',
      'period',
      'calculated_at',
      'period_days',
    ];

    for (const name of mustAllow) {
      expect(
        isForbiddenFieldName(name),
        `Pattern should allow '${name}' but blocked it`,
      ).toBe(false);
    }
  });

  it('extractAllKeys finds declared fields in a simple ZodObject', () => {
    const testSchema = z.object({
      id: z.string(),
      count: z.number(),
      nested: z.object({ value: z.boolean() }),
    });
    const keys = extractAllKeys(testSchema);
    expect(keys).toContain('id');
    expect(keys).toContain('count');
    expect(keys).toContain('nested');
    expect(keys).toContain('value');
  });

  it('extractAllKeys finds fields inside nullable and optional wrappers', () => {
    const testSchema = z.object({
      data: z.object({
        metric: z.number().nullable(),
        label: z.string().optional(),
      }).nullable(),
    });
    const keys = extractAllKeys(testSchema);
    expect(keys).toContain('data');
    expect(keys).toContain('metric');
    expect(keys).toContain('label');
  });

  it('extractAllKeys finds fields inside arrays of objects', () => {
    const testSchema = z.object({
      items: z.array(z.object({
        key: z.string(),
        age_days: z.number(),
      })),
    });
    const keys = extractAllKeys(testSchema);
    expect(keys).toContain('items');
    expect(keys).toContain('key');
    expect(keys).toContain('age_days');
  });

  it('SCHEMA_REGISTRY has the expected number of schemas', () => {
    expect(SCHEMA_REGISTRY.length).toBe(6);
  });
});

// ---------------------------------------------------------------------------
// Main anti-surveillance gate: no schema may declare forbidden fields
// ---------------------------------------------------------------------------

describe('Anti-surveillance: no forbidden fields in any metrics schema', () => {
  it.each(SCHEMA_REGISTRY)(
    'schema $name has no forbidden individual-author fields',
    ({ name, schema }) => {
      const allKeys = extractAllKeys(schema);
      const violations = allKeys.filter((fieldName) => {
        if (!isForbiddenFieldName(fieldName)) return false;
        // Check allow-list
        return !EXPLICIT_ALLOWLIST.has(`${name}.${fieldName}`);
      });

      expect(violations).toEqual(violations.length === 0 ? [] : violations);

      if (violations.length > 0) {
        throw new Error(
          `Anti-surveillance contract violated in schema '${name}'!\n` +
          `Forbidden fields found: ${violations.join(', ')}\n\n` +
          `Rationale: PULSE is anti-surveillance by design. All metrics schemas\n` +
          `must aggregate at squad/team/repo/project level. Individual developer\n` +
          `identifiers must NEVER be declared in Zod contract schemas.\n\n` +
          `If this field is legitimately needed (unusual), add it to\n` +
          `EXPLICIT_ALLOWLIST in anti-surveillance-schemas.test.ts with rationale.`,
        );
      }
    },
  );
});

// ---------------------------------------------------------------------------
// Additional: verify FlowHealthResponse.AgingWipItem has no author/assignee
// ---------------------------------------------------------------------------

describe('Anti-surveillance: AgingWipItem specific checks', () => {
  it('FlowHealthResponse AgingWipItem declares no author or assignee field', () => {
    // AgingWipItem is the highest-risk schema: it describes individual work items.
    // The Pydantic model explicitly documents that it omits assignee/author.
    // This test verifies the Zod mirror upholds the same contract.
    const allKeys = extractAllKeys(FlowHealthResponseSchema);

    // These must never appear as declared schema keys
    const criticalForbidden = ['assignee', 'author', 'reporter', 'committer', 'login', 'email'];
    for (const forbidden of criticalForbidden) {
      expect(allKeys, `FlowHealthResponse schema must not declare '${forbidden}'`).not.toContain(
        forbidden,
      );
    }
  });
});
