/**
 * PULSE — E2E Smoke: Home Dashboard loads successfully
 *
 * Jornada: usuário abre a raiz `/`, o dashboard carrega com sidebar,
 * pelo menos um KPI card renderiza conteúdo real, e o seletor de squad
 * está acessível.
 *
 * PRÉ-REQUISITO: backend docker + vite dev server rodando.
 * Se o backend não responder, o teste faz skip gracioso.
 *
 * Notas de design:
 * - NÃO usamos `waitUntil: 'networkidle'` porque TanStack Query com
 *   `refetchInterval: 60s` mantém polling que nunca deixa a rede "idle".
 * - O TanStack Query no contexto headless leva ~16-20s para completar
 *   o primeiro fetch (cold-start do browser + proxy Vite + load do backend).
 *   Timeout do passo 4b é 35s para margem segura com 2 workers paralelos.
 *
 * Esta é a jornada #1 do E2E Platform (Sprint 1.2, passo 2).
 * Veja: tests/e2e/platform/README.md
 */

import { test, expect } from '@playwright/test';

// Timeout global do teste — generoso porque o primeiro render do dashboard
// faz múltiplas API calls em paralelo via proxy Vite e leva ~20s no headless.
test.setTimeout(60_000);

// ── Helpers ─────────────────────────────────────────────────────────────────

/**
 * Detecta se o dev server está offline.
 * Retorna `true` quando deve pular o teste.
 */
async function devServerIsDown(page: import('@playwright/test').Page): Promise<boolean> {
  try {
    const response = await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 10_000 });
    return response === null || response.status() >= 500;
  } catch {
    return true;
  }
}

// ── Smoke test ───────────────────────────────────────────────────────────────

test.describe('Home Dashboard smoke', () => {
  /**
   * Passo 1: Navegar para /
   * Passo 2: Título "PULSE Dashboard" visível em <10s
   * Passo 3: Sidebar mostra itens de navegação (≥8 links)
   * Passo 4a: Estrutura dos grupos KPI (DORA + Flow) presente imediatamente
   * Passo 4b: Pelo menos um KPI card com conteúdo real (não skeleton) em <35s
   * Passo 5: Seletor de squad presente e acessível
   */
  test('loads title, sidebar, at least one KPI card and the squad selector', async ({ page }) => {
    // Guard: pula graciosamente se o Vite dev server estiver irresponsivo
    const offline = await devServerIsDown(page);
    test.skip(offline, 'Vite dev server não está respondendo — skip do smoke');

    // ── Passo 1: Navegação ─────────────────────────────────────────
    // Usamos `load` (evento DOM load): determinístico e não afetado pelo
    // polling periódico do TanStack Query (refetchInterval: 60s).
    await page.goto('/', { waitUntil: 'load', timeout: 20_000 });

    // ── Passo 2: Título da página ──────────────────────────────────
    // O h1 "PULSE Dashboard" está hardcoded no JSX de HomePage.
    // Renderiza assim que o React hidrata — rápido, mas damos 10s de margem.
    await expect(
      page.getByRole('heading', { name: 'PULSE Dashboard', level: 1 }),
    ).toBeVisible({ timeout: 10_000 });

    // ── Passo 3: Sidebar com itens de navegação ────────────────────
    // Sidebar.tsx renderiza <aside> (role=complementary) contendo <nav>
    // e <ul> com li > Link para cada item do NAV_ITEMS (10 entradas).
    // Capabilities podem ocultar "Sprints" — aceitamos ≥8 links.
    const sidebar = page.getByRole('complementary'); // <aside>
    await expect(sidebar).toBeVisible({ timeout: 5_000 });

    const navLinks = sidebar.getByRole('link');
    // Aguardar pelo menos o primeiro link canônico antes de contar
    await expect(sidebar.getByRole('link', { name: 'Home' })).toBeVisible({ timeout: 5_000 });
    const navLinkCount = await navLinks.count();
    expect(navLinkCount, `Sidebar deveria ter ≥8 links de navegação, tem ${navLinkCount}`).toBeGreaterThan(7);

    // Links canônicos que sempre existem (sem requiresCapability)
    await expect(sidebar.getByRole('link', { name: 'DORA' })).toBeVisible();
    await expect(sidebar.getByRole('link', { name: 'Open PRs' })).toBeVisible();

    // ── Passo 4a: Estrutura dos grupos KPI ────────────────────────
    // KpiGroup renderiza <article aria-labelledby="grp-dora|grp-flow">.
    // Aparece imediatamente (com skeleton dentro) — confirma que o layout
    // do dashboard carregou, independentemente do dado da API.
    const doraGroup = page.locator('article[aria-labelledby="grp-dora"]');
    const flowGroup = page.locator('article[aria-labelledby="grp-flow"]');
    await expect(doraGroup).toBeVisible({ timeout: 5_000 });
    await expect(flowGroup).toBeVisible({ timeout: 5_000 });

    // ── Passo 4b: KPI card com conteúdo real (não skeleton) ────────
    // KpiCard renderiza <div role="group" aria-label="<label>: <value> <unit>">
    // quando tem dado (ex: "Deploy Freq: 11.1 deploys/day").
    // KpiCardSkeleton é <div animate-pulse> sem role="group" — invisível ao seletor.
    //
    // Timing medido em diagnóstico: ~16s com 1 worker, até 30s com 2 workers
    // simultâneos (backend sob carga dupla). Timeout de 35s é a margem segura.
    const kpiCards = page.locator('[role="group"][aria-label]');

    // toPass faz retry automático até o timeout — robusto para variação de timing
    await expect(async () => {
      const count = await kpiCards.count();
      expect(count, 'Nenhum KPI card renderizado — todos ainda em skeleton').toBeGreaterThan(0);

      // Verifica que pelo menos um card tem aria-label com ":" (dado real vs vazio)
      // Cards sem dado têm aria-label="<label>" (sem ":") — ex: "Time to Restore"
      let foundWithData = false;
      for (let i = 0; i < count; i++) {
        const label = await kpiCards.nth(i).getAttribute('aria-label');
        if (label?.includes(':')) {
          foundWithData = true;
          break;
        }
      }
      expect(foundWithData, 'Nenhum KPI card com dado real (aria-label contendo ":")').toBe(true);
    }).toPass({ timeout: 35_000, intervals: [1_000] });

    // ── Passo 5: Seletor de squad ──────────────────────────────────
    // TeamCombobox renderiza no TopBar:
    //   <label for="dash-team-trigger">Squad</label>
    //   <button id="dash-team-trigger" aria-haspopup="listbox">Todas as squads (N)</button>
    //
    // Localizamos pelo id estável — o label "Squad" aparece uppercase via CSS
    // mas o texto DOM é "Squad" (htmlFor referência).
    const squadTrigger = page.locator('#dash-team-trigger');
    await expect(squadTrigger).toBeVisible({ timeout: 5_000 });
    await expect(squadTrigger).toBeEnabled();

    // Confirma que é o combobox customizado (aria-haspopup)
    await expect(squadTrigger).toHaveAttribute('aria-haspopup', 'listbox');

    // Label associada ao trigger deve existir
    const squadLabel = page.locator('label[for="dash-team-trigger"]');
    await expect(squadLabel).toBeVisible();
  });
});
