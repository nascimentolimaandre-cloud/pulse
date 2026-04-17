/**
 * formatDuration — normalize duration values (in hours) into a primary/secondary
 * display pair for KpiCard time metrics.
 *
 * Rules (approved by pulse-ux-reviewer, FDD-DSH-084, 2026-04-17):
 * | Input (hours)            | primary          | secondary       |
 * | ------------------------ | ---------------- | --------------- |
 * | null / NaN / !isFinite   | "—"              | null            |
 * | < 1/60 (<1 min)          | "<1 min"         | null            |
 * | < 1h                     | "Xmin"           | "(0,75h)"       |
 * | 1h ≤ v < 24h             | "X,Xh"           | null            |
 * | ≥ 24h                    | "X,X dias"       | "(X,Xh)"        |
 *
 * Formatting:
 * - Integers: no decimals ("96h", "16 dias").
 * - Decimals: 1 casa após vírgula PT-BR ("16,9 dias", "96,3h").
 * - secondary já vem com parênteses no retorno.
 */

export interface FormattedDuration {
  primary: string;
  secondary: string | null;
}

/**
 * Format a number using PT-BR locale with a fixed fraction digits count.
 * When digits=0 we emit a pure integer string ("96"); when digits>0 we always
 * emit exactly that many decimals ("4,0", "16,9").
 */
function fmtPtBr(n: number, digits: number): string {
  return n.toLocaleString('pt-BR', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatDuration(hours: number | null): FormattedDuration {
  if (hours === null || hours === undefined || Number.isNaN(hours) || !Number.isFinite(hours)) {
    return { primary: '—', secondary: null };
  }

  // <1 min — degenerate bucket, no secondary
  if (hours < 1 / 60) {
    return { primary: '<1 min', secondary: null };
  }

  // < 1h — show in minutes, secondary holds the hour equivalent (2 decimais)
  if (hours < 1) {
    const minutes = Math.round(hours * 60);
    return {
      primary: `${minutes}min`,
      secondary: `(${fmtPtBr(Number(hours.toFixed(2)), 2)}h)`,
    };
  }

  // 1h ≤ v < 24h — hours only, no secondary
  if (hours < 24) {
    // Keep integer formatting when input is a whole hour, else 1 decimal.
    const digits = Number.isInteger(hours) ? 0 : 1;
    return { primary: `${fmtPtBr(hours, digits)}h`, secondary: null };
  }

  // ≥ 24h — days primary, hours secondary.
  // Primary in integer form only when both hours is integer and divides evenly
  // into 24h days; otherwise keep 1 decimal (e.g. 96.3h → "4,0 dias").
  const days = hours / 24;
  const primaryDigits = Number.isInteger(hours) && Number.isInteger(days) ? 0 : 1;
  const secondaryDigits = Number.isInteger(hours) ? 0 : 1;
  return {
    primary: `${fmtPtBr(days, primaryDigits)} dias`,
    secondary: `(${fmtPtBr(hours, secondaryDigits)}h)`,
  };
}
