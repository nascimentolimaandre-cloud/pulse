import { useEffect, useMemo, useRef, useState } from 'react';
import { ChevronDown, Search } from 'lucide-react';
import type { TeamHealth } from '@/types/pipeline';

interface TeamComboboxProps {
  teams: TeamHealth[];
  value: string; // 'default' = all
  onChange: (teamId: string) => void;
}

export function TeamCombobox({ teams, value, onChange }: TeamComboboxProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && open) setOpen(false);
    }
    document.addEventListener('mousedown', onClickOutside);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClickOutside);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  useEffect(() => {
    if (open) {
      setQuery('');
      const t = setTimeout(() => searchRef.current?.focus(), 30);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [open]);

  const grouped = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const map = new Map<string, TeamHealth[]>();
    // FDD-PIPE-001: sort by tier first (active before marginal/dormant), then PRs.
    const sorted = [...teams].sort((a, b) => {
      const tierOrder = { active: 0, marginal: 1, dormant: 2 } as const;
      const ta = tierOrder[a.tier] ?? 1;
      const tb = tierOrder[b.tier] ?? 1;
      if (ta !== tb) return ta - tb;
      return (b.prCount ?? 0) - (a.prCount ?? 0);
    });
    for (const t of sorted) {
      if (needle) {
        const hay = `${t.name} ${t.tribe ?? ''} ${t.squadKey}`.toLowerCase();
        if (!hay.includes(needle)) continue;
      }
      const tribe = t.tribe ?? '—';
      if (!map.has(tribe)) map.set(tribe, []);
      map.get(tribe)!.push(t);
    }
    return Array.from(map.entries());
  }, [teams, query]);

  // FDD-PIPE-001: Tier badge styling — surfaces "marginal/dormant" as a subtle
  // hint without hiding the squad. "active" gets no badge to avoid noise.
  const tierBadge = (tier: TeamHealth['tier']) => {
    if (tier === 'active') return null;
    const label = tier === 'marginal' ? 'Marginal' : 'Dormante';
    const cls =
      tier === 'marginal'
        ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300'
        : 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300';
    return (
      <span
        className={`ml-1.5 inline-flex shrink-0 items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${cls}`}
        title={
          tier === 'marginal'
            ? 'Atividade baixa de PRs — métricas podem não ser confiáveis'
            : 'Sem PRs recentes — squad com atividade só em issues'
        }
      >
        {label}
      </span>
    );
  };

  const currentName =
    value === 'default'
      ? `Todas as squads${teams.length ? ` (${teams.length})` : ''}`
      : teams.find((t) => t.id === value)?.name ?? 'Squad';

  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor="dash-team-trigger"
        className="text-[11px] font-medium uppercase tracking-wide text-content-secondary"
      >
        Squad
      </label>
      <div ref={rootRef} className="relative">
        <button
          id="dash-team-trigger"
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls="dash-team-list"
          onClick={() => setOpen((o) => !o)}
          className="inline-flex h-9 min-w-[220px] items-center justify-between gap-2 rounded-button border border-border-default bg-surface-primary px-3 text-sm text-content-primary transition-colors hover:border-content-tertiary focus:border-brand-primary focus:outline-none focus:ring-2 focus:ring-brand-primary focus:ring-offset-1"
        >
          <span className="truncate">{currentName}</span>
          <ChevronDown className="h-4 w-4 shrink-0 text-content-tertiary" aria-hidden="true" />
        </button>

        {open && (
          <div
            id="dash-team-list"
            role="listbox"
            aria-label="Lista de squads"
            className="absolute left-0 top-[calc(100%+4px)] z-40 w-[320px] max-w-[90vw] rounded-card border border-border-default bg-surface-primary p-2 shadow-elevated"
          >
            <div className="relative mb-1.5">
              <Search
                className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-content-tertiary"
                aria-hidden="true"
              />
              <input
                ref={searchRef}
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Buscar squad ou tribo…"
                aria-label="Buscar squad"
                className="h-8 w-full rounded-button border border-border-default bg-surface-primary pl-7 pr-2 text-sm text-content-primary focus:border-brand-primary focus:outline-none focus:ring-1 focus:ring-brand-primary"
              />
            </div>
            <ul className="max-h-[260px] overflow-y-auto">
              <li
                role="option"
                aria-selected={value === 'default'}
                onClick={() => {
                  onChange('default');
                  setOpen(false);
                }}
                className={`flex cursor-pointer items-center justify-between rounded-md px-2.5 py-2 text-sm ${
                  value === 'default'
                    ? 'bg-brand-light text-brand-primary-hover'
                    : 'text-content-primary hover:bg-surface-secondary'
                }`}
              >
                <span>Todas as squads</span>
                <span className="text-[11px] text-content-tertiary">{teams.length}</span>
              </li>

              {grouped.map(([tribe, list]) => (
                <li key={tribe} className="mt-1">
                  <div className="px-2.5 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-widest text-content-tertiary">
                    {tribe}
                  </div>
                  <ul>
                    {list.map((t) => (
                      <li
                        key={t.id}
                        role="option"
                        aria-selected={value === t.id}
                        onClick={() => {
                          onChange(t.id);
                          setOpen(false);
                        }}
                        className={`flex cursor-pointer items-center justify-between rounded-md px-2.5 py-1.5 text-sm ${
                          value === t.id
                            ? 'bg-brand-light text-brand-primary-hover'
                            : 'text-content-primary hover:bg-surface-secondary'
                        }`}
                      >
                        <span className="flex min-w-0 items-center">
                          <span className="truncate">{t.name}</span>
                          {tierBadge(t.tier)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}

              {grouped.length === 0 && (
                <li className="px-2.5 py-3 text-center text-xs text-content-tertiary">
                  Nenhum resultado para "{query}"
                </li>
              )}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
