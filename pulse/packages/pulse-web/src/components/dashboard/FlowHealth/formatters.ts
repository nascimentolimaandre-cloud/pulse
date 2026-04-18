/**
 * Small formatters for Flow Health — days, status dots, grouping.
 * Kept module-local so we don't pollute the broader dashboard lib.
 */

import type { AgingWipItem, AgingWipSquadRow, StatusCategory } from '@/types/flowHealth';

/**
 * Humanised age — sub-24h renders in hours (per spec §10, Q6), otherwise
 * one-decimal days with PT-BR comma.
 */
export function formatAge(days: number | null): string {
  if (days === null || days === undefined || !Number.isFinite(days)) return '—';
  if (days < 1) {
    const hours = Math.max(1, Math.round(days * 24));
    return `${hours}h`;
  }
  const rounded = Math.round(days * 10) / 10;
  return `${rounded.toString().replace('.', ',')}d`;
}

/** Format 0..1 ratio as integer % ("42%"). */
export function formatPct(v: number | null): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—';
  return `${Math.round(v * 100)}%`;
}

export function statusCategoryLabel(c: StatusCategory): string {
  return c === 'in_review' ? 'Em Review' : 'Em Progresso';
}

/**
 * Aggregate items by squad — used by the item|squad toggle.
 * at_risk_pct = at_risk_count / wip_count (0..1).
 */
export function aggregateBySquad(items: AgingWipItem[]): AgingWipSquadRow[] {
  const bySquad = new Map<string, { wip: number; atRisk: number; maxAge: number }>();
  for (const it of items) {
    const key = it.squad_key ?? '—';
    const row = bySquad.get(key) ?? { wip: 0, atRisk: 0, maxAge: 0 };
    row.wip += 1;
    if (it.is_at_risk) row.atRisk += 1;
    if (it.age_days > row.maxAge) row.maxAge = it.age_days;
    bySquad.set(key, row);
  }
  const out: AgingWipSquadRow[] = [];
  for (const [squad_key, v] of bySquad) {
    out.push({
      squad_key,
      wip_count: v.wip,
      at_risk_count: v.atRisk,
      at_risk_pct: v.wip > 0 ? v.atRisk / v.wip : 0,
      max_age_days: v.maxAge,
    });
  }
  // Sort by at_risk_count desc, then max_age desc.
  out.sort((a, b) => b.at_risk_count - a.at_risk_count || b.max_age_days - a.max_age_days);
  return out;
}
