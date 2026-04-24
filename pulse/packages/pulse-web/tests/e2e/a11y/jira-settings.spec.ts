/**
 * PULSE — A11y audit: Jira admin settings (catalog tab)
 *
 * Scans /settings/integrations/jira/catalog. Heavy admin UI: project
 * catalog table with 69 rows (9 active + 60 discovered), row actions
 * (activate/pause/block), PII-flag tooltip, bulk selection. High-risk
 * surface for focus-management + tooltip a11y.
 */

import { test, expect } from '@playwright/test';
import { runA11yAudit, devServerIsDown } from './_helpers';

test.setTimeout(60_000);

test.describe('a11y — Jira admin settings (catalog)', () => {
  test('no critical/serious WCAG AA violations on first render', async ({ page }, testInfo) => {
    const offline = await devServerIsDown(page);
    test.skip(offline, 'Vite dev server não está respondendo — skip do audit');

    await page.goto('/settings/integrations/jira/catalog', {
      waitUntil: 'load',
      timeout: 20_000,
    });

    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible({
      timeout: 15_000,
    });

    // Catalog loads 69 projects; give it time.
    await page.waitForTimeout(5_000);

    await runA11yAudit(page, testInfo, {
      context: 'jira-settings-catalog',
      disableRules: ['color-contrast'],
    });
  });
});
