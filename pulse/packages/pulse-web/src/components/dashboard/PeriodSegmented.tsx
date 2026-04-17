import type { PeriodOption } from '@/stores/filterStore';

interface PeriodSegmentedProps {
  value: PeriodOption;
  onChange: (p: PeriodOption) => void;
}

const OPTIONS: { id: PeriodOption; label: string }[] = [
  { id: '30d', label: '30d' },
  { id: '60d', label: '60d' },
  { id: '90d', label: '90d' },
  { id: '120d', label: '120d' },
  { id: 'custom', label: 'Personalizado' },
];

export function PeriodSegmented({ value, onChange }: PeriodSegmentedProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <span
        id="period-label"
        className="text-[11px] font-medium uppercase tracking-wide text-content-secondary"
      >
        Período
      </span>
      <div
        role="radiogroup"
        aria-labelledby="period-label"
        className="inline-flex rounded-button bg-surface-tertiary p-[3px]"
      >
        {OPTIONS.map((opt) => {
          const active = value === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(opt.id)}
              className={`h-[30px] rounded-[6px] px-3 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-brand-primary focus:ring-offset-1 ${
                active
                  ? 'bg-surface-primary text-content-primary shadow-card'
                  : 'text-content-secondary hover:text-content-primary'
              }`}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
