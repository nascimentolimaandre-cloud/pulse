/**
 * PULSE — Accessibility audit helper (axe-core + Playwright)
 *
 * Central place to run a consistent a11y audit across pages.
 *
 * Gate policy (Sprint 1.2 passo 4):
 *   - critical + serious  → FAIL the test (block merge)
 *   - moderate + minor    → warn-only (logged, do not fail)
 *   - best-practice tags  → excluded from ruleset (advisory, not WCAG)
 *
 * This matches the WCAG AA compromise in the frontend-design-doc.
 * moderate/minor are logged so we build a baseline and can tighten the
 * gate later without a "big-bang" fix session.
 *
 * Per-page allowlist: pass `disableRules` or `exclude` when a finding is
 * a known-accepted exception (e.g. third-party chart lib). Always document
 * the exception inline — never silent.
 */

import { AxeBuilder } from '@axe-core/playwright';
import { expect, type Page, type TestInfo } from '@playwright/test';

type Severity = 'critical' | 'serious' | 'moderate' | 'minor';

interface RunA11yOptions {
  /** Identifier for logs/attachments (e.g. "home", "dora"). */
  context: string;
  /** CSS selectors to exclude from the scan (rare — prefer fixing the violation). */
  exclude?: string[];
  /** axe-core rule IDs to disable (e.g. "color-contrast" for a known exception). Always document inline why. */
  disableRules?: string[];
}

/**
 * Run an axe-core audit against the current page state and enforce the gate.
 *
 * Call this AFTER the page has reached its steady state (all skeletons
 * resolved, charts rendered). axe-core checks the live DOM — if KPI cards
 * are still in skeleton mode, you'll audit the skeleton, not the content.
 *
 * @throws if any critical or serious violation is detected.
 */
export async function runA11yAudit(
  page: Page,
  testInfo: TestInfo,
  options: RunA11yOptions,
): Promise<void> {
  const { context, exclude = [], disableRules = [] } = options;

  let builder = new AxeBuilder({ page })
    // WCAG 2.1 A + AA is our target per frontend-design-doc.
    // "best-practice" is excluded intentionally — it's advisory, not WCAG,
    // and introduces opinionated checks (e.g. heading-order) that can fight
    // with valid design patterns. Revisit in Sprint 3.
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']);

  for (const selector of exclude) {
    builder = builder.exclude(selector);
  }

  if (disableRules.length > 0) {
    builder = builder.disableRules(disableRules);
  }

  const results = await builder.analyze();

  // Bucket by severity.
  const buckets: Record<Severity, typeof results.violations> = {
    critical: [],
    serious: [],
    moderate: [],
    minor: [],
  };
  for (const v of results.violations) {
    const impact = (v.impact ?? 'minor') as Severity;
    if (impact in buckets) {
      buckets[impact].push(v);
    }
  }

  // Always attach the full JSON report for debugging — available in
  // playwright-report on CI and locally.
  await testInfo.attach(`a11y-${context}.json`, {
    body: JSON.stringify(
      {
        url: page.url(),
        counts: {
          critical: buckets.critical.length,
          serious: buckets.serious.length,
          moderate: buckets.moderate.length,
          minor: buckets.minor.length,
          passes: results.passes.length,
          incomplete: results.incomplete.length,
        },
        violations: results.violations.map((v) => ({
          id: v.id,
          impact: v.impact,
          help: v.help,
          helpUrl: v.helpUrl,
          nodes: v.nodes.map((n) => ({ target: n.target, html: n.html.slice(0, 200) })),
        })),
      },
      null,
      2,
    ),
    contentType: 'application/json',
  });

  // Log warn-level findings to stderr so they surface in the test output
  // without failing the run. Format is greppable for CI log parsing later.
  for (const v of [...buckets.moderate, ...buckets.minor]) {
    // eslint-disable-next-line no-console
    console.warn(
      `[a11y/${context}] WARN ${v.impact}/${v.id}: ${v.help} (${v.nodes.length} nodes) — ${v.helpUrl}`,
    );
  }

  // Pretty summary in the test log, regardless of outcome.
  // eslint-disable-next-line no-console
  console.log(
    `[a11y/${context}] critical=${buckets.critical.length} serious=${buckets.serious.length} moderate=${buckets.moderate.length} minor=${buckets.minor.length} passes=${results.passes.length}`,
  );

  // Gate: fail on critical or serious.
  if (buckets.critical.length > 0 || buckets.serious.length > 0) {
    const lines: string[] = [
      `[a11y/${context}] gate FAILED — ${buckets.critical.length} critical + ${buckets.serious.length} serious violations`,
    ];
    for (const v of [...buckets.critical, ...buckets.serious]) {
      lines.push(`  • ${v.impact}/${v.id}: ${v.help}`);
      lines.push(`    ${v.helpUrl}`);
      for (const n of v.nodes.slice(0, 3)) {
        lines.push(`    → ${n.target.join(' > ')}`);
      }
      if (v.nodes.length > 3) {
        lines.push(`    ...and ${v.nodes.length - 3} more nodes`);
      }
    }
    // Throw via expect for clean Playwright diagnostics.
    expect(
      buckets.critical.length + buckets.serious.length,
      lines.join('\n'),
    ).toBe(0);
  }
}

/**
 * Graceful skip helper — matches the pattern in home-dashboard-smoke.spec.ts.
 * a11y audits only make sense against a live render, so skip cleanly when
 * the dev server is unreachable (mirrors the smoke test behavior).
 */
export async function devServerIsDown(page: Page): Promise<boolean> {
  try {
    const response = await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 10_000 });
    return response === null || response.status() >= 500;
  } catch {
    return true;
  }
}
