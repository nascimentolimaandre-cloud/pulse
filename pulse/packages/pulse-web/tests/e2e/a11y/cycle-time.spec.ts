/**
 * PULSE — A11y audit: Cycle Time page
 *
 * Scans /metrics/cycle-time. This page is chart-heavy (percentile
 * distribution + bottleneck breakdown) — useful to catch SVG/canvas
 * a11y regressions early.
 */

import { test, expect } from '@playwright/test';
import { runA11yAudit, devServerIsDown } from './_helpers';

test.setTimeout(60_000);

test.describe('a11y — Cycle Time page', () => {
  test('no critical/serious WCAG AA violations on first render', async ({ page }, testInfo) => {
    const offline = await devServerIsDown(page);
    test.skip(offline, 'Vite dev server não está respondendo — skip do audit');

    await page.goto('/metrics/cycle-time', { waitUntil: 'load', timeout: 20_000 });

    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible({
      timeout: 15_000,
    });

    // Same 3s settle window as dora.spec.ts — see comment there.
    // eslint-disable-next-line playwright/no-wait-for-timeout
    await page.waitForTimeout(3_000);

    await runA11yAudit(page, testInfo, {
      context: 'cycle-time',
      // TEMP: color-contrast disabled pending FDD-OPS-003.
      disableRules: ['color-contrast'],
    });
  });
});
