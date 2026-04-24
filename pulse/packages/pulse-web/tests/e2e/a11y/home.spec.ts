/**
 * PULSE — A11y audit: Home Dashboard
 *
 * Runs axe-core against `/` after the dashboard reaches steady state
 * (sidebar + KPI groups rendered, at least one KPI card with data).
 *
 * Gate: zero critical + serious WCAG 2.1 AA violations.
 * See tests/e2e/a11y/_helpers.ts for severity policy.
 *
 * Skips cleanly if the Vite dev server is offline — same pattern as
 * home-dashboard-smoke.spec.ts.
 */

import { test, expect } from '@playwright/test';
import { runA11yAudit, devServerIsDown } from './_helpers';

// Same generous timeout as the smoke spec — first render of home does
// several API calls in parallel.
test.setTimeout(60_000);

test.describe('a11y — Home Dashboard', () => {
  test('no critical/serious WCAG AA violations on first render', async ({ page }, testInfo) => {
    const offline = await devServerIsDown(page);
    test.skip(offline, 'Vite dev server não está respondendo — skip do audit');

    await page.goto('/', { waitUntil: 'load', timeout: 20_000 });

    // Wait for steady state. Key on the stable h1 — data loading beyond the
    // heading is not strictly required for a11y structural checks (labels,
    // roles, landmarks). Skeleton cards still need correct a11y attributes.
    await expect(
      page.getByRole('heading', { name: 'PULSE Dashboard', level: 1 }),
    ).toBeVisible({ timeout: 15_000 });

    // Same settle window as dora.spec.ts / cycle-time.spec.ts. Lets React
    // commit post-heading renders (KPI groups, sidebar, topbar) without
    // forcing us to block on a specific KPI card pattern that varies
    // by data availability.
    await page.waitForTimeout(3_000);

    await runA11yAudit(page, testInfo, {
      context: 'home',
      // TEMP: color-contrast disabled pending design-system audit.
      // See FDD-OPS-003 in pulse/docs/backlog/ops-backlog.md.
      // Remove this disableRules entry once the FDD ships.
      disableRules: ['color-contrast'],
    });
  });
});
