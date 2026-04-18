/**
 * Issue type taxonomy → label + token-class. Colours come from design tokens
 * (chart-*) so dark-mode / theme swaps work without touching this file.
 */
import type { IssueType } from '@/types/flowHealth';

export interface IssueTypeMeta {
  label: string;
  /** Tailwind classes for the small pill (bg + text). */
  className: string;
}

export function issueTypeMeta(type: IssueType | null | undefined): IssueTypeMeta {
  const key = (type ?? '').toLowerCase();
  switch (key) {
    case 'epic':
      return { label: 'Épico', className: 'bg-chart-4/15 text-chart-4' };
    case 'story':
      return { label: 'História', className: 'bg-chart-1/15 text-chart-1' };
    case 'task':
      return { label: 'Task', className: 'bg-chart-3/15 text-chart-3' };
    case 'bug':
      return { label: 'Bug', className: 'bg-status-dangerBg text-status-dangerText' };
    case 'subtask':
      return { label: 'Subtask', className: 'bg-surface-tertiary text-content-secondary' };
    default:
      return {
        label: type ? titleCase(type) : 'Item',
        className: 'bg-surface-tertiary text-content-secondary',
      };
  }
}

function titleCase(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
}

/** Classification of risk percentage for colour mapping. */
export function riskTone(pct: number): 'healthy' | 'warning' | 'danger' {
  if (pct < 0.1) return 'healthy';
  if (pct < 0.3) return 'warning';
  return 'danger';
}
