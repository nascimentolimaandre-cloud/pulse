import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import {
  useDiscoveryStatusQuery,
  useDiscoveryTriggerMutation,
} from '@/hooks/useJiraAdmin';

export function DiscoveryTriggerButton() {
  const [showConfirm, setShowConfirm] = useState(false);
  const { data: status } = useDiscoveryStatusQuery();
  const trigger = useDiscoveryTriggerMutation();
  const isRunning = status?.inFlight ?? false;

  function handleTrigger() {
    setShowConfirm(false);
    trigger.mutate();
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setShowConfirm(true)}
        disabled={isRunning || trigger.isPending}
        className="inline-flex items-center gap-2 rounded-button bg-brand-primary px-4 py-2 text-sm font-medium text-content-inverse transition-colors hover:bg-brand-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
        aria-label="Iniciar descoberta de projetos Jira"
      >
        <RefreshCw className={`h-4 w-4 ${isRunning ? 'animate-spin' : ''}`} />
        {isRunning ? 'Descobrindo...' : 'Descobrir agora'}
      </button>

      {/* Confirmation dialog overlay */}
      {showConfirm && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          role="dialog"
          aria-modal="true"
          aria-labelledby="discovery-confirm-title"
        >
          <div className="mx-4 w-full max-w-sm rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card">
            <h3
              id="discovery-confirm-title"
              className="mb-2 text-base font-semibold text-content-primary"
            >
              Confirmar descoberta
            </h3>
            <p className="mb-4 text-sm text-content-secondary">
              Isso iniciara uma busca por novos projetos Jira no seu tenant. O processo pode levar
              alguns minutos dependendo do numero de projetos.
            </p>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowConfirm(false)}
                className="rounded-button border border-border-default px-4 py-2 text-sm font-medium text-content-primary transition-colors hover:bg-surface-tertiary"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={handleTrigger}
                className="rounded-button bg-brand-primary px-4 py-2 text-sm font-medium text-content-inverse transition-colors hover:bg-brand-primary-hover"
              >
                Confirmar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
