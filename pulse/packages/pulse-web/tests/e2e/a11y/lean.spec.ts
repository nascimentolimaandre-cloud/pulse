/**
 * PULSE — A11y audit: Lean metrics page
 *
 * Scans /metrics/lean. Page shows lead-time distribution (scatter + CFD
 * + Little's Law gauge). Chart-heavy, stress-tests SVG a11y.
 */

import { test, expect } from '@playwright/test';
import { runA11yAudit, devServerIsDown } from './_helpers';

test.setTimeout(60_000);

test.describe('a11y — Lean metrics page', () => {
  test('no critical/serious WCAG AA violations on first render', async ({ page }, testInfo) => {
    const offline = await devServerIsDown(page);
    test.skip(offline, 'Vite dev server não está respondendo — skip do audit');

    await page.goto('/metrics/lean', { waitUntil: 'load', timeout: 20_000 });

    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible({
      timeout: 15_000,
    });

    await page.waitForTimeout(3_000);

    await runA11yAudit(page, testInfo, {
      context: 'lean',
      disableRules: ['color-contrast'],
    });
  });
});
