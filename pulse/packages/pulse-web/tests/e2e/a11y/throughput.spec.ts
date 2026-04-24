/**
 * PULSE — A11y audit: Throughput metrics page
 *
 * Scans /metrics/throughput. Page shows PR throughput trends + per-author
 * analytics (opaque bag). Common a11y traps here: chart SVGs without
 * <title>, author table without caption/scope.
 */

import { test, expect } from '@playwright/test';
import { runA11yAudit, devServerIsDown } from './_helpers';

test.setTimeout(60_000);

test.describe('a11y — Throughput page', () => {
  test('no critical/serious WCAG AA violations on first render', async ({ page }, testInfo) => {
    const offline = await devServerIsDown(page);
    test.skip(offline, 'Vite dev server não está respondendo — skip do audit');

    await page.goto('/metrics/throughput', { waitUntil: 'load', timeout: 20_000 });

    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible({
      timeout: 15_000,
    });

    // 3s settle window — same rationale as dora.spec.ts.
    await page.waitForTimeout(3_000);

    await runA11yAudit(page, testInfo, {
      context: 'throughput',
      // TEMP: color-contrast disabled pending FDD-OPS-003.
      disableRules: ['color-contrast'],
    });
  });
});
