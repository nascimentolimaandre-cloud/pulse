import { useState } from 'react';

interface DateRangeFilterProps {
  startDate: string | null;
  endDate: string | null;
  onSubmit: (start: string, end: string) => void;
}

const MAX_DAYS = 365;
const MS_DAY = 86_400_000;

export function DateRangeFilter({ startDate, endDate, onSubmit }: DateRangeFilterProps) {
  const [start, setStart] = useState(startDate ?? '');
  const [end, setEnd] = useState(endDate ?? '');
  const [error, setError] = useState<string | null>(null);

  function validateAndSubmit() {
    if (!start || !end) {
      setError('Selecione ambas as datas.');
      return;
    }
    const s = new Date(start).getTime();
    const e = new Date(end).getTime();
    if (Number.isNaN(s) || Number.isNaN(e)) {
      setError('Datas inválidas.');
      return;
    }
    if (s >= e) {
      setError('A data inicial deve ser anterior à final.');
      return;
    }
    const days = Math.round((e - s) / MS_DAY);
    if (days > MAX_DAYS) {
      setError('Período máximo: 365 dias.');
      return;
    }
    setError(null);
    onSubmit(start, end);
  }

  return (
    <div className="flex flex-col gap-1.5" role="group" aria-label="Intervalo personalizado">
      <span className="text-[11px] font-medium uppercase tracking-wide text-content-secondary">
        Intervalo
      </span>
      <div className="flex items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-[10px] text-content-tertiary">De</span>
          <input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="h-8 rounded-button border border-border-default bg-surface-primary px-2 font-mono text-xs text-content-primary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
            aria-label="Data inicial"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[10px] text-content-tertiary">Até</span>
          <input
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="h-8 rounded-button border border-border-default bg-surface-primary px-2 font-mono text-xs text-content-primary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
            aria-label="Data final"
          />
        </label>
        <button
          type="button"
          onClick={validateAndSubmit}
          className="h-8 rounded-button border border-border-default bg-surface-primary px-3 text-xs font-medium text-content-primary hover:border-brand-primary hover:text-brand-primary focus:outline-none focus:ring-2 focus:ring-brand-primary focus:ring-offset-1"
        >
          Aplicar
        </button>
      </div>
      {error && (
        <p role="alert" className="text-[11px] text-status-danger">
          {error}
        </p>
      )}
    </div>
  );
}
