import { ChevronDown } from 'lucide-react';
import { useFilterStore } from '@/stores/filterStore';
import type { PeriodOption } from '@/stores/filterStore';

interface PeriodOptionConfig {
  value: PeriodOption;
  label: string;
}

const PERIOD_OPTIONS: PeriodOptionConfig[] = [
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: '90d', label: 'Last 90 days' },
];

export function TopBar() {
  const { teamId, period, setTeamId, setPeriod } = useFilterStore();

  return (
    <header className="flex h-14 items-center justify-between border-b border-border-default bg-surface-primary px-page-padding">
      {/* Left: Breadcrumb placeholder */}
      <div className="text-sm text-content-secondary">
        {/* Breadcrumb will be populated by route context */}
      </div>

      {/* Right: Global Filters */}
      <div className="flex items-center gap-3">
        {/* Team Dropdown */}
        <div className="relative">
          <select
            value={teamId}
            onChange={(e) => setTeamId(e.target.value)}
            className="appearance-none rounded-button border border-border-default bg-surface-primary py-1.5 pl-3 pr-8 text-sm text-content-primary transition-colors hover:border-content-tertiary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
            aria-label="Select team"
          >
            <option value="default">All Teams</option>
            {/* Teams will be populated from API */}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-content-tertiary" />
        </div>

        {/* Period Dropdown */}
        <div className="relative">
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value as PeriodOption)}
            className="appearance-none rounded-button border border-border-default bg-surface-primary py-1.5 pl-3 pr-8 text-sm text-content-primary transition-colors hover:border-content-tertiary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
            aria-label="Select period"
          >
            {PERIOD_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-content-tertiary" />
        </div>
      </div>
    </header>
  );
}
