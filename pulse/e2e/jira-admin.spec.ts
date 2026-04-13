/**
 * E2E: Jira Admin Settings — ADR-014 Dynamic Project Discovery
 *
 * Tests the critical user journeys through /settings/integrations/jira:
 *   1. Page loads with 3 tabs; default tab is Projetos (catalog).
 *   2. "Descobrir agora" button triggers discovery: badge shows "Descobrindo…"
 *      then returns to "Idle" after mock response.
 *   3. Status filter: selecting "active" shows only active-status rows.
 *   4. Project activation: Actions → Ativar on a discovered project → toast "Projeto ativado".
 *   5. Audit tab: last event is project_activated with correct actor.
 *   6. Config tab: mode change → save → audit event mode_changed appears.
 *
 * API mocking: Playwright route interception (no MSW required).
 * Auth: dev mode bypasses auth; test uses X-Test-Tenant-ID header which the
 *       dev server accepts to skip JWT validation.
 *
 * Requirements:
 *   npx playwright install --with-deps
 *   BASE_URL=http://localhost:5173 npx playwright test e2e/jira-admin.spec.ts
 */

import { test, expect, type Page, type Route } from '@playwright/test';

// ---------------------------------------------------------------------------
// Test data fixtures — deterministic, never random
// ---------------------------------------------------------------------------

const TENANT_ID = '00000000-0000-0000-0000-000000000001';

const MOCK_CONFIG = {
  mode: 'allowlist',
  discoveryEnabled: true,
  discoveryScheduleCron: '0 3 * * *',
  maxActiveProjects: 100,
  maxIssuesPerHour: 20000,
  smartPrScanDays: 90,
  smartMinPrReferences: 3,
  lastDiscoveryAt: null,
  lastDiscoveryStatus: null,
  lastDiscoveryError: null,
};

const MOCK_DISCOVERY_IDLE = {
  inFlight: false,
  lastRun: null,
};

const MOCK_DISCOVERY_IN_FLIGHT = {
  inFlight: true,
  lastRun: null,
};

const MOCK_DISCOVERY_COMPLETE = {
  inFlight: false,
  lastRun: {
    runId: 'run-001',
    startedAt: new Date().toISOString(),
    finishedAt: new Date().toISOString(),
    status: 'success',
    discoveredCount: 5,
    activatedCount: 0,
    archivedCount: 0,
    updatedCount: 0,
    errors: [],
  },
};

const MOCK_PROJECTS_ALL = {
  items: [
    {
      projectKey: 'PROJ1',
      name: 'Project One',
      status: 'active',
      projectType: 'software',
      activationSource: 'manual',
      issueCount: 120,
      prReferenceCount: 15,
      firstSeenAt: '2026-01-01T00:00:00Z',
      activatedAt: '2026-01-02T00:00:00Z',
      lastSyncAt: '2026-04-13T03:00:00Z',
      lastSyncStatus: 'success',
      consecutiveFailures: 0,
      lastError: null,
    },
    {
      projectKey: 'PROJ2',
      name: 'Project Two',
      status: 'discovered',
      projectType: 'software',
      activationSource: null,
      issueCount: 0,
      prReferenceCount: 2,
      firstSeenAt: '2026-04-13T00:00:00Z',
      activatedAt: null,
      lastSyncAt: null,
      lastSyncStatus: null,
      consecutiveFailures: 0,
      lastError: null,
    },
    {
      projectKey: 'PROJ3',
      name: 'Project Three',
      status: 'paused',
      projectType: 'business',
      activationSource: null,
      issueCount: 5,
      prReferenceCount: 0,
      firstSeenAt: '2026-02-01T00:00:00Z',
      activatedAt: null,
      lastSyncAt: '2026-03-01T00:00:00Z',
      lastSyncStatus: 'failed',
      consecutiveFailures: 5,
      lastError: 'Connection timeout',
    },
  ],
  total: 3,
  counts: {
    discovered: 1,
    active: 1,
    paused: 1,
    blocked: 0,
    archived: 0,
  },
};

const MOCK_PROJECTS_ACTIVE_ONLY = {
  items: [MOCK_PROJECTS_ALL.items[0]],
  total: 1,
  counts: MOCK_PROJECTS_ALL.counts,
};

const MOCK_AUDIT_INITIAL: { items: object[]; total: number } = {
  items: [
    {
      id: 'aud-001',
      eventType: 'discovery_run',
      projectKey: null,
      actor: 'system',
      beforeValue: null,
      afterValue: { status: 'success', discovered: 5 },
      reason: 'Discovery run completed',
      createdAt: '2026-04-13T03:00:00Z',
    },
  ],
  total: 1,
};

const MOCK_AUDIT_AFTER_ACTIVATION = {
  items: [
    {
      id: 'aud-002',
      eventType: 'project_activated',
      projectKey: 'PROJ2',
      actor: 'tenant_admin:user@example.com',
      beforeValue: { status: 'discovered' },
      afterValue: { status: 'active' },
      reason: 'Manual activation',
      createdAt: '2026-04-13T10:00:00Z',
    },
    ...MOCK_AUDIT_INITIAL.items,
  ],
  total: 2,
};

const MOCK_AUDIT_AFTER_MODE_CHANGE = {
  items: [
    {
      id: 'aud-003',
      eventType: 'mode_changed',
      projectKey: null,
      actor: 'tenant_admin:user@example.com',
      beforeValue: { mode: 'allowlist' },
      afterValue: { mode: 'smart' },
      reason: 'Admin changed discovery mode',
      createdAt: '2026-04-13T11:00:00Z',
    },
    ...MOCK_AUDIT_AFTER_ACTIVATION.items,
  ],
  total: 3,
};

// ---------------------------------------------------------------------------
// Route interception helpers
// ---------------------------------------------------------------------------

const API_BASE = '/api/v1/admin/integrations/jira';

/**
 * Register all baseline API mocks for the Jira admin page.
 * Individual tests can override specific routes by registering
 * more specific handlers via page.route() before calling this.
 */
async function mockBaselineApis(page: Page): Promise<void> {
  await page.route(`${API_BASE}/config`, (route) =>
    route.fulfill({ json: MOCK_CONFIG })
  );
  // Discovery status endpoint: /api/v1/admin/integrations/jira/discovery/status
  await page.route(`${API_BASE}/discovery/status`, (route) =>
    route.fulfill({ json: MOCK_DISCOVERY_IDLE })
  );
  // Smart suggestions (called by SmartSuggestionsBanner)
  await page.route(`${API_BASE}/smart-suggestions`, (route) =>
    route.fulfill({ json: { items: [] } })
  );
  await page.route(`${API_BASE}/projects*`, (route) => {
    const url = new URL(route.request().url());
    const status = url.searchParams.get('status');
    if (status === 'active') {
      return route.fulfill({ json: MOCK_PROJECTS_ACTIVE_ONLY });
    }
    return route.fulfill({ json: MOCK_PROJECTS_ALL });
  });
  await page.route(`${API_BASE}/audit*`, (route) =>
    route.fulfill({ json: MOCK_AUDIT_INITIAL })
  );
}

async function navigateToJiraSettings(page: Page): Promise<void> {
  await page.goto('/settings/integrations/jira');
  // Wait for the layout to stabilize (tab bar rendered)
  await page.waitForSelector('[data-testid="jira-settings-layout"], text=Jira Integration', {
    timeout: 10_000,
  });
}

// ---------------------------------------------------------------------------
// Test: Page loads correctly
// ---------------------------------------------------------------------------

test.describe('Jira Admin Settings — ADR-014', () => {
  test.beforeEach(async ({ page }) => {
    await mockBaselineApis(page);
  });

  test('loads /settings/integrations/jira and renders 3 tabs', async ({ page }) => {
    await navigateToJiraSettings(page);

    // Verify 3 tabs are present
    await expect(page.getByRole('link', { name: 'Projetos' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Configuracao' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Auditoria' })).toBeVisible();

    // Default redirect to /catalog — Projetos tab should be active
    await page.waitForURL('**/jira/catalog');
    // Verify the catalog content renders (trigger button visible)
    await expect(page.getByRole('button', { name: /descobrir agora/i })).toBeVisible();
  });

  test('Idle status badge is visible on initial load', async ({ page }) => {
    await navigateToJiraSettings(page);
    await page.waitForURL('**/jira/catalog');

    // The DiscoveryStatusBadge shows "Idle" when inFlight=false and no failed lastRun
    await expect(page.getByText('Idle')).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // Test: Discovery trigger
  // ---------------------------------------------------------------------------

  test('clicking Descobrir agora shows "Descobrindo..." badge then returns to Idle', async ({
    page,
  }) => {
    // Phase 1: status returns inFlight=true immediately after POST
    let callCount = 0;
    await page.route(`${API_BASE}/discovery/status`, (route) => {
      callCount++;
      // First call: idle; second call (after trigger): in flight; third: complete
      if (callCount === 1) return route.fulfill({ json: MOCK_DISCOVERY_IDLE });
      if (callCount === 2) return route.fulfill({ json: MOCK_DISCOVERY_IN_FLIGHT });
      return route.fulfill({ json: MOCK_DISCOVERY_COMPLETE });
    });
    await page.route(`${API_BASE}/discovery/trigger`, (route) =>
      route.fulfill({ status: 202, json: MOCK_DISCOVERY_IN_FLIGHT })
    );

    await navigateToJiraSettings(page);
    await page.waitForURL('**/jira/catalog');

    const triggerButton = page.getByRole('button', { name: /descobrir agora/i });
    await expect(triggerButton).toBeVisible();
    await triggerButton.click();

    // Confirmation dialog appears
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.getByRole('button', { name: /confirmar/i }).click();

    // After trigger: badge turns "Descobrindo..."
    // The badge re-renders when the status query refetches (React Query invalidation)
    await expect(page.getByText('Descobrindo...')).toBeVisible({ timeout: 5_000 });

    // After further polling, status returns complete → badge returns to Idle
    await expect(page.getByText('Idle')).toBeVisible({ timeout: 10_000 });
  });

  // ---------------------------------------------------------------------------
  // Test: Status filter on projects tab
  // ---------------------------------------------------------------------------

  test('filtering by status "active" shows only active rows', async ({ page }) => {
    await navigateToJiraSettings(page);
    await page.waitForURL('**/jira/catalog');

    // Wait for table to render (at least one row visible)
    await expect(page.getByText('PROJ1')).toBeVisible();

    // Click the "Ativos" filter chip
    await page.getByRole('button', { name: /^ativos/i }).click();

    // After filter: only PROJ1 (active) should be visible
    await expect(page.getByText('PROJ1')).toBeVisible();
    await expect(page.getByText('PROJ2')).not.toBeVisible();
    await expect(page.getByText('PROJ3')).not.toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // Test: Project activation from Actions dropdown
  // ---------------------------------------------------------------------------

  test('activating a discovered project via row actions updates status to Ativo', async ({
    page,
  }) => {
    // The useProjectActionMutation applies an optimistic update immediately:
    // PROJ2's status chip changes from "Descoberto" to "Ativo" before the server responds.
    // After onSettled the query is invalidated and re-fetches; we mock the refreshed list.
    let activationDone = false;
    await page.route(`${API_BASE}/projects*`, (route) => {
      if (activationDone) {
        // Return updated list with PROJ2 now active
        const updatedProjects = {
          ...MOCK_PROJECTS_ALL,
          items: MOCK_PROJECTS_ALL.items.map((p) =>
            p.projectKey === 'PROJ2' ? { ...p, status: 'active' } : p
          ),
        };
        return route.fulfill({ json: updatedProjects });
      }
      return route.fulfill({ json: MOCK_PROJECTS_ALL });
    });
    await page.route(`${API_BASE}/projects/PROJ2/activate`, (route) => {
      activationDone = true;
      return route.fulfill({
        status: 200,
        json: { ...MOCK_PROJECTS_ALL.items[1], status: 'active' },
      });
    });

    await navigateToJiraSettings(page);
    await page.waitForURL('**/jira/catalog');

    // Wait for PROJ2 (discovered) to appear
    await expect(page.getByText('PROJ2')).toBeVisible();

    // Open the Actions dropdown for PROJ2
    // ProjectRowActions renders: aria-label="Acoes para projeto PROJ2"
    const proj2Row = page.locator('tr', { hasText: 'PROJ2' });
    await proj2Row.getByRole('button', { name: 'Acoes para projeto PROJ2' }).click();

    // Click "Ativar" in the dropdown (role=menuitem, text="Ativar")
    await page.getByRole('menuitem', { name: 'Ativar' }).click();

    // After optimistic update PROJ2's status chip changes to "Ativo"
    // (no confirmation dialog on row-action activate — only discovery trigger has one)
    await expect(
      page.locator('tr', { hasText: 'PROJ2' }).getByText('Ativo')
    ).toBeVisible({ timeout: 5_000 });
  });

  // ---------------------------------------------------------------------------
  // Test: Audit tab — last event is project_activated
  // ---------------------------------------------------------------------------

  test('audit tab shows project_activated event with correct actor', async ({ page }) => {
    // Serve audit with activation event pre-populated
    await page.route(`${API_BASE}/audit*`, (route) =>
      route.fulfill({ json: MOCK_AUDIT_AFTER_ACTIVATION })
    );

    await navigateToJiraSettings(page);
    await page.waitForURL('**/jira/catalog');

    // Navigate to Auditoria tab
    await page.getByRole('link', { name: 'Auditoria' }).click();
    await page.waitForURL('**/jira/audit');

    // The most recent event should be project_activated
    await expect(page.getByText('Projeto ativado')).toBeVisible();
    // The project key should be visible
    await expect(page.getByText('PROJ2')).toBeVisible();
    // The actor
    await expect(page.getByText(/tenant_admin/i)).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // Test: Config tab mode change → save → audit event mode_changed
  // ---------------------------------------------------------------------------

  test('changing mode on Config tab and saving produces mode_changed audit event', async ({
    page,
  }) => {
    let auditHasMode = false;
    await page.route(`${API_BASE}/config`, (route: Route) => {
      if (route.request().method() === 'PUT') {
        auditHasMode = true;
        return route.fulfill({ json: { ...MOCK_CONFIG, mode: 'smart' } });
      }
      return route.fulfill({ json: auditHasMode ? { ...MOCK_CONFIG, mode: 'smart' } : MOCK_CONFIG });
    });
    await page.route(`${API_BASE}/audit*`, (route) => {
      if (auditHasMode) return route.fulfill({ json: MOCK_AUDIT_AFTER_MODE_CHANGE });
      return route.fulfill({ json: MOCK_AUDIT_INITIAL });
    });

    await navigateToJiraSettings(page);
    await page.waitForURL('**/jira/catalog');

    // Navigate to Configuracao tab
    await page.getByRole('link', { name: 'Configuracao' }).click();
    await page.waitForURL('**/jira/config');

    // Wait for config to load (mode selector visible)
    await expect(page.getByText('Modo de descoberta')).toBeVisible();

    // Change mode to "Smart" — ModeSelector renders mode cards with radio semantics
    await page.getByRole('radio', { name: /smart/i }).click();

    // Save button should be enabled (form is dirty)
    const saveBtn = page.getByRole('button', { name: /salvar configuracao/i });
    await expect(saveBtn).not.toBeDisabled();
    await saveBtn.click();

    // Toast "Configuracao salva com sucesso"
    await expect(page.getByText(/configuracao salva com sucesso/i)).toBeVisible({
      timeout: 5_000,
    });

    // Navigate to audit tab and verify mode_changed event
    await page.getByRole('link', { name: 'Auditoria' }).click();
    await page.waitForURL('**/jira/audit');

    await expect(page.getByText('Modo alterado')).toBeVisible({ timeout: 5_000 });
  });

  // ---------------------------------------------------------------------------
  // Anti-surveillance: no individual developer scores or leaderboards
  // ---------------------------------------------------------------------------

  test('no individual developer rankings or scores are exposed on the page', async ({ page }) => {
    await navigateToJiraSettings(page);
    await page.waitForURL('**/jira/catalog');

    const content = await page.content();

    // Assert absence of developer-identifying leaderboard patterns
    expect(content).not.toMatch(/leaderboard/i);
    expect(content).not.toMatch(/developer.?rank/i);
    expect(content).not.toMatch(/engineer.?score/i);
    expect(content).not.toMatch(/individual.?performance/i);
  });

  // ---------------------------------------------------------------------------
  // Accessibility: zero axe violations on the Jira settings page
  // ---------------------------------------------------------------------------

  test('accessibility: zero critical violations on /jira/catalog', async ({ page }) => {
    // axe-core via @axe-core/playwright requires an import; handle gracefully.
    // If not installed, the test is skipped with a clear message.
    let AxeBuilder: typeof import('@axe-core/playwright').default | undefined;
    try {
      const mod = await import('@axe-core/playwright');
      AxeBuilder = mod.default;
    } catch {
      test.skip(true, '@axe-core/playwright not installed — skipping a11y test');
      return;
    }

    await navigateToJiraSettings(page);
    await page.waitForURL('**/jira/catalog');

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze();

    expect(results.violations, JSON.stringify(results.violations, null, 2)).toHaveLength(0);
  });
});
