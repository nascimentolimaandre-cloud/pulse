/**
 * PULSE — A11y audit: Open PRs page
 *
 * Scans /prs. Large table of open pull requests with filters + status
 * chips. Tables are a classic a11y trap (missing caption, improper
 * scope attrs, row-header ambiguity).
 */

import { test, expect } from '@playwright/test';
import { runA11yAudit, devServerIsDown } from './_helpers';

test.setTimeout(60_000);

test.describe('a11y — Open PRs page', () => {
  test('no critical/serious WCAG AA violations on first render', async ({ page }, testInfo) => {
    const offline = await devServerIsDown(page);
    test.skip(offline, 'Vite dev server não está respondendo — skip do audit');

    await page.goto('/prs', { waitUntil: 'load', timeout: 20_000 });

    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible({
      timeout: 15_000,
    });

    await page.waitForTimeout(3_000);

    await runA11yAudit(page, testInfo, {
      context: 'prs',
      disableRules: ['color-contrast'],
    });
  });
});
