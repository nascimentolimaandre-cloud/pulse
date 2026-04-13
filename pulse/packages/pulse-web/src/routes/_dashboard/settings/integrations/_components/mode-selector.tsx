import { Zap, Shield, ShieldOff, Brain, AlertTriangle } from 'lucide-react';
import type { JiraDiscoveryMode } from '@pulse/shared';

interface ModeOption {
  mode: JiraDiscoveryMode;
  label: string;
  description: string;
  guidance: string;
  icon: React.ComponentType<{ className?: string }>;
}

const MODE_OPTIONS: ModeOption[] = [
  {
    mode: 'auto',
    label: 'Automatico',
    description: 'Todos os projetos descobertos ficam ativos. Blocklist pode bloquear.',
    guidance: 'Use quando quer onboarding rapido e baixa friccao.',
    icon: Zap,
  },
  {
    mode: 'allowlist',
    label: 'Allowlist',
    description: 'Apenas projetos aprovados manualmente sao sincronizados.',
    guidance: 'Use em ambientes regulados ou quando precisa de governanca total.',
    icon: Shield,
  },
  {
    mode: 'blocklist',
    label: 'Blocklist',
    description: 'Todos ativos exceto projetos explicitamente bloqueados.',
    guidance: 'Use quando quer controle seletivo sobre o que NAO sincronizar.',
    icon: ShieldOff,
  },
  {
    mode: 'smart',
    label: 'Smart',
    description: 'Ativa automaticamente projetos referenciados em PRs acima do threshold.',
    guidance: 'Recomendado para times de engenharia que usam PRs com chave Jira.',
    icon: Brain,
  },
];

interface ModeSelectorProps {
  value: JiraDiscoveryMode;
  onChange: (mode: JiraDiscoveryMode) => void;
  disabled?: boolean;
}

export function ModeSelector({ value, onChange, disabled }: ModeSelectorProps) {
  const showPiiBanner = value === 'auto' || value === 'smart';

  return (
    <div>
      <fieldset className="grid grid-cols-1 gap-3 sm:grid-cols-2" disabled={disabled}>
        <legend className="sr-only">Modo de descoberta Jira</legend>
        {MODE_OPTIONS.map((option) => {
        const isSelected = value === option.mode;
        const Icon = option.icon;

        return (
          <label
            key={option.mode}
            className={`
              flex cursor-pointer gap-3 rounded-card border-2 p-card-padding transition-colors
              ${
                isSelected
                  ? 'border-brand-primary bg-brand-light'
                  : 'border-border-default bg-surface-primary hover:border-border-hover'
              }
              ${disabled ? 'cursor-not-allowed opacity-60' : ''}
            `}
          >
            <input
              type="radio"
              name="jira-discovery-mode"
              value={option.mode}
              checked={isSelected}
              onChange={() => onChange(option.mode)}
              className="sr-only"
              aria-label={`Modo ${option.label}`}
            />
            <div
              className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-button ${
                isSelected ? 'bg-brand-primary text-content-inverse' : 'bg-surface-tertiary text-content-secondary'
              }`}
            >
              <Icon className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <p
                className={`text-sm font-semibold ${
                  isSelected ? 'text-brand-primary' : 'text-content-primary'
                }`}
              >
                {option.label}
              </p>
              <p className="mt-0.5 text-xs text-content-secondary">{option.description}</p>
              <p className="mt-1 text-xs italic text-content-tertiary">{option.guidance}</p>
            </div>
          </label>
        );
      })}
      </fieldset>

      {showPiiBanner && (
        <div
          className="mt-3 flex items-start gap-2 rounded-card border border-status-warning/30 bg-amber-50 p-3"
          role="alert"
          data-testid="pii-mode-warning"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-status-warning" aria-hidden="true" />
          <p className="text-xs text-content-secondary">
            No modo {value === 'auto' ? 'Auto' : 'Smart'}, projetos Jira acess&#237;veis pelo seu
            token ser&#227;o ativados automaticamente. Se houver projetos sens&#237;veis (RH,
            Jur&#237;dico, Finan&#231;as, Confidencial), eles ficar&#227;o marcados como
            &ldquo;discovered&rdquo; exigindo aprova&#231;&#227;o manual.
          </p>
        </div>
      )}
    </div>
  );
}
