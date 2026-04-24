/**
 * PULSE — A11y audit: Pipeline Monitor page
 *
 * Scans /pipeline-monitor. Information-dense ops dashboard: per-source
 * status cards, per-team health table, schema drift alerts, coverage
 * panel. Many custom status chips — frequent source of aria-label gaps.
 */

import { test, expect } from '@playwright/test';
import { runA11yAudit, devServerIsDown } from './_helpers';

test.setTimeout(60_000);

test.describe('a11y — Pipeline Monitor page', () => {
  test('no critical/serious WCAG AA violations on first render', async ({ page }, testInfo) => {
    const offline = await devServerIsDown(page);
    test.skip(offline, 'Vite dev server não está respondendo — skip do audit');

    await page.goto('/pipeline-monitor', { waitUntil: 'load', timeout: 20_000 });

    // Pipeline Monitor has no headings in its connected state (only the
    // empty-state has an h2 "Conecte sua primeira fonte"). Wait on the
    // <main> landmark instead — it's always present in the layout.
    // A11y backlog: page SHOULD declare a top-level heading (WCAG 2.4.6 /
    // best-practice). Tracked under the a11y backlog for polish.
    await expect(page.getByRole('main')).toBeVisible({ timeout: 15_000 });

    // Pipeline Monitor has heavier initial load — health table fetches
    // per-team status for all 27 squads. 5s settle instead of 3s.
    await page.waitForTimeout(5_000);

    await runA11yAudit(page, testInfo, {
      context: 'pipeline-monitor',
      disableRules: ['color-contrast'],
    });
  });
});
