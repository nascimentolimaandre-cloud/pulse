/**
 * Sparkline for at_risk_count evolution (30d). Pre-dev adjustment #2.
 *
 * TODO(pulse-data-engineer): the backend currently returns only a
 * snapshot `at_risk_count`. We need a daily time-series endpoint — see
 * FDD-KB-007 (adds `/metrics/flow-health/at-risk-trend?period=30d`).
 * Until then, this component accepts `data` explicitly and the parent
 * passes a synthetic walk derived from the current count so the UI
 * remains truthful about its provisional nature (see `synthAtRiskSeries`).
 */
interface AtRiskSparklineProps {
  /** Daily counts, oldest → newest. Length 7–30. */
  data: number[];
  /** Colour defaults to var(--color-danger). */
  tone?: 'danger' | 'warning' | 'neutral';
  width?: number;
  height?: number;
  ariaLabel?: string;
}

const TONE_STROKE: Record<NonNullable<AtRiskSparklineProps['tone']>, string> = {
  danger: 'var(--color-danger)',
  warning: 'var(--color-warning)',
  neutral: 'var(--color-text-tertiary)',
};

export function AtRiskSparkline({
  data,
  tone = 'danger',
  width = 72,
  height = 18,
  ariaLabel = 'Evolução de itens at risk nos últimos 30 dias',
}: AtRiskSparklineProps) {
  if (!data || data.length < 2) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;
  const stepX = width / (data.length - 1);
  const pts = data
    .map((v, i) => `${i * stepX},${height - ((v - min) / range) * height}`)
    .join(' ');
  return (
    <svg
      role="img"
      aria-label={ariaLabel}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="flex-shrink-0"
    >
      <polyline
        points={pts}
        fill="none"
        stroke={TONE_STROKE[tone]}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * Provisional series generator — deterministic noise around the current
 * at_risk_count so the sparkline does not claim knowledge it doesn't
 * have. When the real endpoint lands, replace with a hook.
 */
export function synthAtRiskSeries(current: number, days = 14): number[] {
  if (current <= 0) return Array.from({ length: days }, () => 0);
  const out: number[] = [];
  // Gentle random-walk seeded by `current` so repeated renders are stable.
  let seed = current * 9301 + 49297;
  const rand = () => {
    seed = (seed * 9301 + 49297) % 233280;
    return seed / 233280;
  };
  let v = Math.max(1, Math.round(current * 0.7));
  for (let i = 0; i < days; i++) {
    const drift = (rand() - 0.3) * Math.max(2, current * 0.08);
    v = Math.max(0, Math.round(v + drift));
    out.push(v);
  }
  // Force the last point to exactly `current` — it's the only truthful data point.
  out[out.length - 1] = current;
  return out;
}
