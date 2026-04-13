import { useState } from 'react';
import { Lightbulb, X } from 'lucide-react';
import { useSmartSuggestionsQuery, useBulkProjectActionMutation } from '@/hooks/useJiraAdmin';

export function SmartSuggestionsBanner() {
  const [dismissed, setDismissed] = useState(false);
  const { data } = useSmartSuggestionsQuery();
  const bulkAction = useBulkProjectActionMutation();

  if (dismissed || !data || data.items.length === 0) {
    return null;
  }

  const keys = data.items.map((s) => s.projectKey);
  const totalPrs = data.items.reduce((sum, s) => sum + s.prReferenceCount, 0);

  function handleActivateAll() {
    bulkAction.mutate({ action: 'activate', projectKeys: keys });
    setDismissed(true);
  }

  return (
    <div className="mb-4 flex items-start gap-3 rounded-card border border-amber-200 bg-amber-50 p-card-padding">
      <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-content-primary">
          {data.items.length} projetos novos ({keys.join(', ')}) aparecem em{' '}
          {totalPrs.toLocaleString()} PRs. Ativar todos?
        </p>
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={handleActivateAll}
            disabled={bulkAction.isPending}
            className="rounded-button bg-brand-primary px-3 py-1.5 text-xs font-medium text-content-inverse transition-colors hover:bg-brand-primary-hover disabled:opacity-50"
          >
            {bulkAction.isPending ? 'Ativando...' : 'Ativar todos'}
          </button>
          <button
            type="button"
            onClick={() => setDismissed(true)}
            className="rounded-button border border-border-default px-3 py-1.5 text-xs font-medium text-content-primary transition-colors hover:bg-surface-tertiary"
          >
            Dispensar
          </button>
        </div>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="shrink-0 text-content-tertiary hover:text-content-primary"
        aria-label="Fechar sugestoes"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
