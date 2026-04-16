import { useState, useMemo } from 'react';
import { Activity } from 'lucide-react';
import { getSeverityConfig } from './shared/status';
import { usePipelineTimeline } from '@/hooks/usePipeline';
import type { TimelineEvent } from '@/types/pipeline';

type FilterKey = 'all' | 'warn+' | 'error';

const FILTERS: Array<{ key: FilterKey; label: string }> = [
  { key: 'all', label: 'Todos' },
  { key: 'warn+', label: 'Warn+' },
  { key: 'error', label: 'Erros' },
];

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('pt-BR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function Skeleton() {
  return (
    <div className="rounded-card border border-border-default bg-surface-primary shadow-card overflow-hidden">
      <div className="py-[12px] px-[16px] border-b border-border-default">
        <div className="h-[16px] w-[100px] bg-surface-tertiary rounded animate-pulse motion-reduce:animate-none" />
      </div>
      <div className="p-[16px] flex flex-col gap-[8px]">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={i}
            className="h-[32px] bg-surface-tertiary rounded animate-pulse motion-reduce:animate-none"
          />
        ))}
      </div>
    </div>
  );
}

export function Timeline() {
  const [filter, setFilter] = useState<FilterKey>('all');
  const { data: events, isLoading } = usePipelineTimeline({ limit: 50 });

  const filtered = useMemo(() => {
    if (!events) return [];
    if (filter === 'all') return events;
    if (filter === 'warn+')
      return events.filter(
        (e) => e.severity === 'warning' || e.severity === 'error'
      );
    return events.filter((e) => e.severity === 'error');
  }, [events, filter]);

  if (isLoading) return <Skeleton />;

  return (
    <div className="rounded-card border border-border-default bg-surface-primary shadow-card overflow-hidden">
      {/* Header */}
      <div className="py-[12px] px-[16px] border-b border-border-default flex items-center justify-between">
        <div className="flex items-center gap-[6px] text-[14px] font-semibold">
          <Activity size={15} className="text-brand-primary" />
          Timeline
        </div>
        <div className="flex gap-[3px]">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`py-[3px] px-[8px] rounded-badge text-[11px] font-medium cursor-pointer border transition-colors
                ${filter === f.key
                  ? 'border-brand-primary bg-brand-primary/[0.06] text-brand-primary'
                  : 'border-border-default bg-transparent text-content-secondary hover:border-content-tertiary'
                }
                focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:outline-none`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* Event list */}
      <div
        className="max-h-[320px] overflow-y-auto py-[4px] px-[16px] pb-[10px]"
        role="log"
        aria-live="polite"
      >
        {filtered.length === 0 ? (
          <div className="py-[18px] text-center text-[13px] text-content-tertiary">
            Nenhum evento
          </div>
        ) : (
          filtered.map((ev, i) => <EventRow key={i} event={ev} />)
        )}
      </div>
    </div>
  );
}

function EventRow({ event }: { event: TimelineEvent }) {
  const sev = getSeverityConfig(event.severity);

  return (
    <div className="flex items-start gap-[10px] py-[6px] border-b border-border-default/[0.03]">
      <div
        className={`w-[7px] h-[7px] rounded-full ${sev.dot} mt-[5px] shrink-0`}
      />
      <div className="flex-1">
        <div className="flex items-center gap-[5px] mb-[2px]">
          <span className="text-[10px] font-mono text-content-tertiary">
            {formatTime(event.ts)}
          </span>
          <span
            className={`text-[9px] font-semibold py-[1px] px-[5px] rounded-badge ${sev.bg} ${sev.text} uppercase`}
          >
            {event.stage}
          </span>
        </div>
        <div className="text-[12px] text-content-primary leading-[1.4]">
          {event.message}
        </div>
      </div>
    </div>
  );
}
