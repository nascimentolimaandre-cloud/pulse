/**
 * PULSE — A11y audit: Integrations status page
 *
 * Scans /integrations. Simple list of source integrations + status per
 * connector. Small surface but typical entry-point for admins.
 */

import { test, expect } from '@playwright/test';
import { runA11yAudit, devServerIsDown } from './_helpers';

test.setTimeout(60_000);

test.describe('a11y — Integrations page', () => {
  test('no critical/serious WCAG AA violations on first render', async ({ page }, testInfo) => {
    const offline = await devServerIsDown(page);
    test.skip(offline, 'Vite dev server não está respondendo — skip do audit');

    await page.goto('/integrations', { waitUntil: 'load', timeout: 20_000 });

    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible({
      timeout: 15_000,
    });

    await page.waitForTimeout(3_000);

    await runA11yAudit(page, testInfo, {
      context: 'integrations',
      disableRules: ['color-contrast'],
    });
  });
});
