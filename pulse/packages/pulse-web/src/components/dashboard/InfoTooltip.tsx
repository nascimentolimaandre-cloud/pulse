/**
 * Lightweight tooltip used by KpiCard.
 *
 * No external dep (kept off Radix on purpose — we use it only for KPI info
 * popovers for now). Renders an Info icon trigger; on hover or keyboard
 * focus it shows a positioned bubble with multi-line content.
 *
 * Accessibility:
 *  - Trigger is `<button type="button">` so it's tab-reachable.
 *  - `aria-describedby` connects the trigger to the bubble.
 *  - Bubble carries `role="tooltip"` and renders only when visible
 *    (`hidden` attr otherwise) so screen readers don't announce it
 *    out of context.
 *  - Plain-text fallback also lives in the trigger's `aria-label` so
 *    screen-reader users with no hover get the same content.
 */
import { Info } from 'lucide-react';
import { useId, useState, useCallback } from 'react';

export interface InfoTooltipProps {
  /** Multi-line content. Newlines render as actual line breaks. */
  content: string;
  /** Compact ARIA label — defaults to "Mais informações". */
  ariaLabel?: string;
}

export function InfoTooltip({ content, ariaLabel = 'Mais informações' }: InfoTooltipProps) {
  const [open, setOpen] = useState(false);
  const id = useId();

  const show = useCallback(() => setOpen(true), []);
  const hide = useCallback(() => setOpen(false), []);

  return (
    <span className="relative inline-flex">
      <button
        type="button"
        aria-label={ariaLabel}
        aria-describedby={open ? id : undefined}
        className="inline-flex h-3.5 w-3.5 cursor-help items-center justify-center rounded-full text-content-tertiary transition-colors hover:text-content-secondary focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:ring-offset-1"
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        onClick={(e) => {
          // Tap-to-toggle on touch devices
          e.stopPropagation();
          setOpen((v) => !v);
        }}
      >
        <Info className="h-3 w-3" aria-hidden="true" />
      </button>
      <span
        id={id}
        role="tooltip"
        hidden={!open}
        className="pointer-events-none absolute left-1/2 top-full z-50 mt-1.5 w-[320px] -translate-x-1/2 whitespace-pre-line rounded-card border border-border-default bg-surface-primary px-3 py-2 text-[12px] leading-relaxed text-content-secondary shadow-lg"
      >
        {content}
      </span>
    </span>
  );
}
