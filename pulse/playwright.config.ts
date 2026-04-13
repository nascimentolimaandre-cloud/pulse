/**
 * Playwright configuration for PULSE E2E tests.
 *
 * Targets the Vite dev server (localhost:5173) by default.
 * Set BASE_URL env var to override (e.g., for staging runs).
 *
 * Run:
 *   cd pulse
 *   npx playwright test                                    # all specs
 *   npx playwright test e2e/jira-admin.spec.ts             # specific spec
 *   npx playwright test --headed                           # with browser UI
 *   npx playwright test --reporter=html                    # HTML report
 */

import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [
    ['list'],
    ['json', { outputFile: 'playwright-report/results.json' }],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
  ],

  use: {
    baseURL: process.env.BASE_URL ?? 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    // Send tenant header for dev-mode auth bypass
    extraHTTPHeaders: {
      'X-Test-Tenant-ID': '00000000-0000-0000-0000-000000000001',
    },
    // Prefer explicit waits — never rely on networkidle
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 5'] },
    },
  ],

  // Start the Vite dev server automatically when running locally
  webServer: process.env.CI
    ? undefined
    : {
        command: 'npm run dev',
        cwd: './packages/pulse-web',
        url: 'http://localhost:5173',
        reuseExistingServer: true,
        timeout: 30_000,
      },
});
