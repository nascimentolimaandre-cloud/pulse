import { defineConfig, devices } from '@playwright/test';

/**
 * PULSE Web — Playwright configuration
 *
 * Browsers: Chromium + Firefox (base coverage).
 * Webkit deferred to Sprint 3 (macOS SSL/font setup overhead not justified now).
 *
 * Test directory convention:
 *   tests/e2e/platform/   ← Platform E2E: universal, qualquer tenant
 *   tests/e2e/            ← Future: shared fixtures, helpers
 *
 * Customer-specific journeys (Webmotors) live in:
 *   tests-customers/webmotors/e2e/   ← NOT covered by this config
 *
 * Pre-requisites before running:
 *   1. docker compose up -d          (API + DB)
 *   2. npm run dev  (or let webServer below start it automatically)
 *
 * See: tests/e2e/platform/README.md
 */
export default defineConfig({
  testDir: './tests/e2e',
  testMatch: '**/*.spec.ts',

  /* Generoso: home faz múltiplas API calls em paralelo no primeiro render */
  timeout: 30_000,
  expect: {
    timeout: 15_000,
  },

  fullyParallel: true,

  /* CI: 2 retries para absorver flakiness de timing de API calls
     Local: 0 retries para feedback rápido — se falhou, olha de verdade */
  retries: process.env.CI ? 2 : 0,

  /* CI serializado (recursos limitados). Local: paralelo livre (ncpus / 2) */
  workers: process.env.CI ? 1 : undefined,

  /* Relatórios */
  reporter: process.env.CI
    ? [['github'], ['html', { outputFolder: 'playwright-report', open: 'never' }]]
    : [['list'], ['html', { outputFolder: 'playwright-report', open: 'on-failure' }]],

  use: {
    baseURL: 'http://localhost:5173',

    /* Trace apenas no primeiro retry — captura estado completo sem inflar storage */
    trace: 'on-first-retry',

    /* Screenshot só em falha — evita overhead em testes verdes */
    screenshot: 'only-on-failure',

    /* Video off por padrão. Habilitar via CLI: --video=on */
    video: 'off',
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
    /* webkit e mobile-chrome reservados para Sprint 3 */
  ],

  /* Auto-start do dev server antes dos testes.
     Se já estiver rodando na porta 5173, reutiliza sem restart (reuseExistingServer).
     Em CI, o server sempre é iniciado do zero. */
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});
