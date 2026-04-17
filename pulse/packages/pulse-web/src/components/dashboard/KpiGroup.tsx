import type { ReactNode } from 'react';

interface KpiGroupProps {
  id: string;
  title: string;
  hint?: string;
  dotColor?: 'dora' | 'flow';
  /** Optional counter shown in the header (e.g., "1 squad em Low") */
  warningCount?: { label: string; count: number };
  children: ReactNode;
}

/**
 * Semantic wrapper around a group of KPI cards (DORA or Flow).
 * Produces an <article> with labelled heading + 4-col grid.
 */
export function KpiGroup({ id, title, hint, dotColor = 'dora', warningCount, children }: KpiGroupProps) {
  const dotClass = dotColor === 'dora' ? 'bg-brand-primary' : 'bg-status-info';

  return (
    <article
      aria-labelledby={id}
      className="rounded-card border border-border-default bg-surface-primary p-card-padding shadow-card"
    >
      <header className="mb-3.5 flex items-baseline justify-between gap-3">
        <h3
          id={id}
          className="flex items-center gap-2 text-[13px] font-semibold uppercase tracking-wide text-content-primary"
        >
          <span className={`inline-block h-2 w-2 rounded-full ${dotClass}`} aria-hidden="true" />
          {title}
        </h3>
        <div className="flex items-center gap-3">
          {warningCount && warningCount.count > 0 && (
            <span
              className="inline-flex items-center gap-1 rounded-badge bg-status-dangerBg px-2 py-0.5 text-xs font-medium text-status-dangerText"
              aria-label={`${warningCount.count} ${warningCount.label}`}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-status-danger" aria-hidden="true" />
              {warningCount.count} {warningCount.label}
            </span>
          )}
          {hint && <span className="text-xs text-content-tertiary">{hint}</span>}
        </div>
      </header>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">{children}</div>
    </article>
  );
}
