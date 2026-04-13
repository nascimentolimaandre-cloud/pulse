import { useState, useEffect, useCallback } from 'react';
import { createRoute } from '@tanstack/react-router';
import { CheckCircle2, AlertCircle, Clock } from 'lucide-react';
import { jiraSettingsRoute } from './jira';
import { ModeSelector } from './_components/mode-selector';
import { DiscoveryTriggerButton } from './_components/discovery-trigger-button';
import { DiscoveryStatusBadge } from './_components/discovery-status-badge';
import {
  useJiraConfigQuery,
  useJiraConfigMutation,
  useDiscoveryStatusQuery,
} from '@/hooks/useJiraAdmin';
import type { JiraDiscoveryMode, UpdateTenantJiraConfigInput } from '@pulse/shared';

export const jiraConfigRoute = createRoute({
  getParentRoute: () => jiraSettingsRoute,
  path: '/config',
  component: JiraConfigTab,
});

function JiraConfigTab() {
  const { data: config, isLoading, isError, error } = useJiraConfigQuery();
  const mutation = useJiraConfigMutation();
  const { data: discoveryStatus, isLoading: discoveryStatusLoading } = useDiscoveryStatusQuery();

  // Local form state
  const [mode, setMode] = useState<JiraDiscoveryMode>('allowlist');
  const [maxActiveProjects, setMaxActiveProjects] = useState(100);
  const [maxIssuesPerHour, setMaxIssuesPerHour] = useState(5000);
  const [smartPrScanDays, setSmartPrScanDays] = useState(90);
  const [smartMinPrReferences, setSmartMinPrReferences] = useState(5);
  const [showToast, setShowToast] = useState(false);

  // Sync form state from server data
  useEffect(() => {
    if (config) {
      setMode(config.mode);
      setMaxActiveProjects(config.maxActiveProjects);
      setMaxIssuesPerHour(config.maxIssuesPerHour);
      setSmartPrScanDays(config.smartPrScanDays);
      setSmartMinPrReferences(config.smartMinPrReferences);
    }
  }, [config]);

  // Dirty check
  const isDirty =
    config != null &&
    (mode !== config.mode ||
      maxActiveProjects !== config.maxActiveProjects ||
      maxIssuesPerHour !== config.maxIssuesPerHour ||
      smartPrScanDays !== config.smartPrScanDays ||
      smartMinPrReferences !== config.smartMinPrReferences);

  const handleSave = useCallback(() => {
    const input: UpdateTenantJiraConfigInput = {
      mode,
      maxActiveProjects,
      maxIssuesPerHour,
      smartPrScanDays,
      smartMinPrReferences,
    };
    mutation.mutate(input, {
      onSuccess: () => {
        setShowToast(true);
        setTimeout(() => setShowToast(false), 3000);
      },
    });
  }, [mode, maxActiveProjects, maxIssuesPerHour, smartPrScanDays, smartMinPrReferences, mutation]);

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <AlertCircle className="mb-4 h-12 w-12 text-status-danger" />
        <h2 className="mb-2 text-lg font-semibold text-content-primary">
          Falha ao carregar configuracao
        </h2>
        <p className="text-sm text-content-secondary">
          {error instanceof Error ? error.message : 'Erro inesperado.'}
        </p>
      </div>
    );
  }

  if (isLoading || !config) {
    return <ConfigSkeleton />;
  }

  return (
    <div className="max-w-2xl space-y-8">
      {/* Mode selector */}
      <section>
        <h2 className="mb-3 text-base font-semibold text-content-primary">
          Modo de descoberta
        </h2>
        <ModeSelector value={mode} onChange={setMode} disabled={mutation.isPending} />
      </section>

      {/* Caps form */}
      <section>
        <h2 className="mb-3 text-base font-semibold text-content-primary">Limites e parametros</h2>
        <div className="space-y-4">
          {/* Max active projects slider */}
          <div>
            <label
              htmlFor="maxActiveProjects"
              className="mb-1 block text-sm font-medium text-content-primary"
            >
              Maximo de projetos ativos: {maxActiveProjects}
            </label>
            <input
              id="maxActiveProjects"
              type="range"
              min={10}
              max={500}
              step={10}
              value={maxActiveProjects}
              onChange={(e) => setMaxActiveProjects(Number(e.target.value))}
              className="w-full accent-brand-primary"
            />
            <div className="flex justify-between text-xs text-content-tertiary">
              <span>10</span>
              <span>500</span>
            </div>
          </div>

          {/* Max issues per hour */}
          <div>
            <label
              htmlFor="maxIssuesPerHour"
              className="mb-1 block text-sm font-medium text-content-primary"
            >
              Max issues por hora
            </label>
            <input
              id="maxIssuesPerHour"
              type="number"
              min={100}
              max={50000}
              step={100}
              value={maxIssuesPerHour}
              onChange={(e) => setMaxIssuesPerHour(Number(e.target.value))}
              className="h-9 w-40 rounded-button border border-border-default bg-surface-primary px-3 text-sm text-content-primary focus:border-brand-primary focus:outline-none"
            />
          </div>

          {/* Discovery schedule (read-only cron display) */}
          <div>
            <label className="mb-1 block text-sm font-medium text-content-primary">
              Agenda de descoberta
            </label>
            <div className="flex items-center gap-2 text-sm text-content-secondary">
              <Clock className="h-4 w-4 text-content-tertiary" />
              <span>{describeCron(config.discoveryScheduleCron)}</span>
              <span className="text-xs text-content-tertiary">
                ({config.discoveryScheduleCron})
              </span>
            </div>
          </div>

          {/* Smart mode params (only relevant when mode=smart) */}
          {mode === 'smart' && (
            <>
              <div>
                <label
                  htmlFor="smartPrScanDays"
                  className="mb-1 block text-sm font-medium text-content-primary"
                >
                  Janela de analise de PRs (dias)
                </label>
                <input
                  id="smartPrScanDays"
                  type="number"
                  min={7}
                  max={365}
                  value={smartPrScanDays}
                  onChange={(e) => setSmartPrScanDays(Number(e.target.value))}
                  className="h-9 w-32 rounded-button border border-border-default bg-surface-primary px-3 text-sm text-content-primary focus:border-brand-primary focus:outline-none"
                />
              </div>
              <div>
                <label
                  htmlFor="smartMinPrReferences"
                  className="mb-1 block text-sm font-medium text-content-primary"
                >
                  Minimo de PRs referenciando
                </label>
                <input
                  id="smartMinPrReferences"
                  type="number"
                  min={1}
                  max={100}
                  value={smartMinPrReferences}
                  onChange={(e) => setSmartMinPrReferences(Number(e.target.value))}
                  className="h-9 w-32 rounded-button border border-border-default bg-surface-primary px-3 text-sm text-content-primary focus:border-brand-primary focus:outline-none"
                />
              </div>
            </>
          )}
        </div>
      </section>

      {/* Save button */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={!isDirty || mutation.isPending}
          className="rounded-button bg-brand-primary px-6 py-2 text-sm font-medium text-content-inverse transition-colors hover:bg-brand-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          {mutation.isPending ? 'Salvando...' : 'Salvar configuracao'}
        </button>

        {mutation.isError && (
          <span className="text-sm text-status-danger">
            Erro ao salvar: {mutation.error.message}
          </span>
        )}
      </div>

      {/* Discovery section */}
      <section className="border-t border-border-default pt-6">
        <h2 className="mb-3 text-base font-semibold text-content-primary">Descoberta</h2>
        <div className="flex items-center gap-4">
          <DiscoveryTriggerButton />
          <DiscoveryStatusBadge status={discoveryStatus} isLoading={discoveryStatusLoading} />
        </div>

        {/* Last discovery summary */}
        {discoveryStatus?.lastRun && (
          <div className="mt-4 rounded-card border border-border-default bg-surface-secondary p-card-padding">
            <h3 className="mb-2 text-sm font-medium text-content-primary">Ultima descoberta</h3>
            <div className="grid grid-cols-2 gap-2 text-xs text-content-secondary sm:grid-cols-4">
              <div>
                <span className="block font-medium text-content-primary">Quando</span>
                {new Date(discoveryStatus.lastRun.startedAt).toLocaleString()}
              </div>
              <div>
                <span className="block font-medium text-content-primary">Descobertos</span>
                {discoveryStatus.lastRun.discoveredCount}
              </div>
              <div>
                <span className="block font-medium text-content-primary">Ativados</span>
                {discoveryStatus.lastRun.activatedCount}
              </div>
              <div>
                <span className="block font-medium text-content-primary">Erros</span>
                {discoveryStatus.lastRun.errors.length}
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Toast */}
      {showToast && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-card border border-emerald-200 bg-emerald-50 px-4 py-3 shadow-card">
          <CheckCircle2 className="h-5 w-5 text-status-success" />
          <span className="text-sm font-medium text-content-primary">
            Configuracao salva com sucesso
          </span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function describeCron(cron: string): string {
  // Simple human-readable description for common patterns
  if (cron === '0 3 * * *') return 'Todo dia as 03:00 UTC';
  if (cron === '0 */6 * * *') return 'A cada 6 horas';
  if (cron === '0 0 * * 1') return 'Toda segunda-feira as 00:00 UTC';
  return cron;
}

function ConfigSkeleton() {
  return (
    <div className="max-w-2xl space-y-8">
      <div className="space-y-3">
        <div className="h-5 w-40 animate-pulse rounded bg-surface-tertiary" />
        <div className="grid grid-cols-2 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-card bg-surface-tertiary" />
          ))}
        </div>
      </div>
      <div className="space-y-3">
        <div className="h-5 w-48 animate-pulse rounded bg-surface-tertiary" />
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-9 w-full animate-pulse rounded bg-surface-tertiary" />
        ))}
      </div>
    </div>
  );
}
