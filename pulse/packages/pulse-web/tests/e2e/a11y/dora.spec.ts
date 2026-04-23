/**
 * PULSE — A11y audit: DORA metrics page
 *
 * Scans /metrics/dora after the page settles. DORA has 4 KPI cards
 * (Deploy Freq, Lead Time for Changes, Change Failure Rate, MTTR) plus
 * trend sparklines — a good stress-test for chart a11y (alt text on SVGs).
 */

import { test, expect } from '@playwright/test';
import { runA11yAudit, devServerIsDown } from './_helpers';

test.setTimeout(60_000);

test.describe('a11y — DORA page', () => {
  test('no critical/serious WCAG AA violations on first render', async ({ page }, testInfo) => {
    const offline = await devServerIsDown(page);
    test.skip(offline, 'Vite dev server não está respondendo — skip do audit');

    await page.goto('/metrics/dora', { waitUntil: 'load', timeout: 20_000 });

    // Wait for steady state. Key on the main h1 — data loading beyond the
    // heading is not required for a11y structural checks (labels, roles,
    // landmarks). Charts without data still need correct a11y attributes.
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible({
      timeout: 15_000,
    });

    // Small settle window to let React commit post-heading renders (sidebar,
    // topbar, skeleton→content transition on visible elements). 3s is a
    // compromise: long enough for first paint, short enough to keep the
    // suite <2min total. (eslint-plugin-playwright would flag this — we
    // don't have that plugin installed; this is a deliberate exception.)
    await page.waitForTimeout(3_000);

    await runA11yAudit(page, testInfo, {
      context: 'dora',
      // TEMP: color-contrast disabled pending FDD-OPS-003.
      disableRules: ['color-contrast'],
    });
  });
});
