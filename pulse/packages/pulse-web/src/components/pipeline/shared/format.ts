/** Format a number with abbreviation: 1.2k, 374k, 1.2M */
export function fmt(n: number | null | undefined): string {
  if (n == null) return '\u2014';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (n >= 1e5) return (n / 1e3).toFixed(0) + 'k';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return n.toLocaleString('pt-BR');
}

/** Format duration in seconds to human-readable */
export function fmtD(s: number | null | undefined): string {
  if (s == null) return '\u2014';
  if (s < 60) return s.toFixed(1) + 's';
  if (s < 3600) return Math.floor(s / 60) + 'm ' + Math.floor(s % 60) + 's';
  return Math.floor(s / 3600) + 'h ' + Math.floor((s % 3600) / 60) + 'm';
}

/** Format ETA: ~18min, ~1h 28min */
export function fmtE(s: number | null | undefined): string {
  if (!s) return '';
  if (s < 60) return '~' + Math.ceil(s) + 's';
  if (s < 3600) return '~' + Math.ceil(s / 60) + 'min';
  return '~' + Math.floor(s / 3600) + 'h ' + Math.ceil((s % 3600) / 60) + 'min';
}

/** Relative time from an ISO timestamp to now: "ha 4min", "ha 2h" */
export function rel(iso: string | null | undefined): string {
  if (!iso) return '\u2014';
  const d = (Date.now() - new Date(iso).getTime()) / 1e3;
  if (d < 0) return 'agora';
  if (d < 60) return 'ha ' + Math.floor(d) + 's';
  if (d < 3600) return 'ha ' + Math.floor(d / 60) + 'min';
  if (d < 86400) return 'ha ' + Math.floor(d / 3600) + 'h';
  return 'ha ' + Math.floor(d / 86400) + 'd';
}

/** Percentage from 0..1 to "22%" */
export function pct(v: number): string {
  return Math.round(v * 100) + '%';
}
