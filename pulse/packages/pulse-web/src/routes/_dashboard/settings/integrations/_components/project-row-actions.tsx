import { useState, useRef, useEffect } from 'react';
import { MoreHorizontal, Play, Pause, Ban, RotateCcw } from 'lucide-react';
import type { JiraProjectStatus } from '@pulse/shared';
import { useProjectActionMutation } from '@/hooks/useJiraAdmin';

interface ActionDef {
  action: 'activate' | 'pause' | 'block' | 'resume';
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  /** Tailwind text color class for the action */
  colorClass: string;
}

/** Returns the set of valid actions for a given project status. */
function getActionsForStatus(status: JiraProjectStatus): ActionDef[] {
  switch (status) {
    case 'discovered':
      return [
        { action: 'activate', label: 'Ativar', icon: Play, colorClass: 'text-status-success' },
        { action: 'block', label: 'Bloquear', icon: Ban, colorClass: 'text-status-danger' },
      ];
    case 'active':
      return [
        { action: 'pause', label: 'Pausar', icon: Pause, colorClass: 'text-status-warning' },
        { action: 'block', label: 'Bloquear', icon: Ban, colorClass: 'text-status-danger' },
      ];
    case 'paused':
      return [
        { action: 'resume', label: 'Retomar', icon: RotateCcw, colorClass: 'text-status-info' },
        { action: 'block', label: 'Bloquear', icon: Ban, colorClass: 'text-status-danger' },
      ];
    case 'blocked':
      return [
        { action: 'resume', label: 'Desbloquear', icon: RotateCcw, colorClass: 'text-status-info' },
      ];
    case 'archived':
      return [];
    default:
      return [];
  }
}

interface ProjectRowActionsProps {
  projectKey: string;
  status: JiraProjectStatus;
}

export function ProjectRowActions({ projectKey, status }: ProjectRowActionsProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const mutation = useProjectActionMutation();
  const actions = getActionsForStatus(status);

  // Close dropdown on outside click
  useEffect(() => {
    if (!open) return;
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function handleEscape(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [open]);

  if (actions.length === 0) return null;

  function handleAction(action: ActionDef['action']) {
    setOpen(false);
    mutation.mutate({ action, projectKey });
  }

  return (
    <div className="relative" ref={menuRef}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="rounded-button p-1.5 text-content-secondary transition-colors hover:bg-surface-tertiary hover:text-content-primary"
        aria-label={`Acoes para projeto ${projectKey}`}
        aria-haspopup="true"
        aria-expanded={open}
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-30 mt-1 min-w-[160px] rounded-card border border-border-default bg-surface-primary py-1 shadow-card"
        >
          {actions.map((a) => {
            const Icon = a.icon;
            return (
              <button
                key={a.action}
                type="button"
                role="menuitem"
                onClick={() => handleAction(a.action)}
                disabled={mutation.isPending}
                className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium transition-colors hover:bg-surface-tertiary disabled:opacity-50"
              >
                <Icon className={`h-4 w-4 ${a.colorClass}`} />
                <span className="text-content-primary">{a.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export { getActionsForStatus };
