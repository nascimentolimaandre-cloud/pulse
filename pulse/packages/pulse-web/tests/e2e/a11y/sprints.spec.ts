/**
 * PULSE — A11y audit: Sprint metrics page
 *
 * Scans /metrics/sprints. Capability-gated — if the tenant doesn't have
 * Sprint capability, the page renders an empty state with explanation.
 * A11y on the empty state is still valid (and common regression surface).
 */

import { test, expect } from '@playwright/test';
import { runA11yAudit, devServerIsDown } from './_helpers';

test.setTimeout(60_000);

test.describe('a11y — Sprint metrics page', () => {
  test('no critical/serious WCAG AA violations on first render', async ({ page }, testInfo) => {
    const offline = await devServerIsDown(page);
    test.skip(offline, 'Vite dev server não está respondendo — skip do audit');

    await page.goto('/metrics/sprints', { waitUntil: 'load', timeout: 20_000 });

    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible({
      timeout: 15_000,
    });

    await page.waitForTimeout(3_000);

    await runA11yAudit(page, testInfo, {
      context: 'sprints',
      disableRules: ['color-contrast'],
    });
  });
});
