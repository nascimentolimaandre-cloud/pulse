import { useState, useMemo } from 'react';
import { Link, useMatchRoute } from '@tanstack/react-router';
import {
  Home,
  Activity,
  Clock,
  BarChart3,
  Workflow,
  Zap,
  GitPullRequest,
  Cable,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
} from 'lucide-react';
import { useTenantCapabilities } from '@/hooks/useTenantCapabilities';
import type { CapabilityKey } from '@/types/tenant';

interface NavItem {
  label: string;
  path: string;
  icon: React.ComponentType<{ className?: string }>;
  /** When set, item is only visible if tenant has this capability. */
  requiresCapability?: CapabilityKey;
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Home', path: '/', icon: Home },
  { label: 'DORA', path: '/metrics/dora', icon: Activity },
  { label: 'Cycle Time', path: '/metrics/cycle-time', icon: Clock },
  { label: 'Throughput', path: '/metrics/throughput', icon: BarChart3 },
  { label: 'Lean & Flow', path: '/metrics/lean', icon: Workflow },
  { label: 'Sprints', path: '/metrics/sprints', icon: Zap, requiresCapability: 'sprints' },
  { label: 'Open PRs', path: '/prs', icon: GitPullRequest },
  { label: 'Integrations', path: '/integrations', icon: Cable },
  { label: 'Pipeline', path: '/pipeline-monitor', icon: Activity },
  { label: 'Jira Settings', path: '/settings/integrations/jira', icon: Settings },
];

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const matchRoute = useMatchRoute();
  const { data: capabilities, isSuccess: capsLoaded } = useTenantCapabilities();

  // Filter capability-gated items only AFTER capabilities resolve successfully.
  // While loading / on error, we keep every item visible to avoid flicker and
  // to fail open if the endpoint is down.
  const visibleItems = useMemo(() => {
    if (!capsLoaded || !capabilities) return NAV_ITEMS;
    return NAV_ITEMS.filter((item) => {
      if (!item.requiresCapability) return true;
      return item.requiresCapability === 'sprints'
        ? capabilities.hasSprints
        : capabilities.hasKanban;
    });
  }, [capsLoaded, capabilities]);

  return (
    <aside
      className={`
        fixed left-0 top-0 h-screen border-r border-border-default
        bg-surface-primary flex flex-col transition-all duration-200
        ${collapsed ? 'w-16' : 'w-60'}
      `}
    >
      {/* Logo */}
      <div className="flex h-14 items-center gap-2 border-b border-border-default px-4">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-button bg-brand-primary">
          <span className="text-sm font-bold text-content-inverse">P</span>
        </div>
        {!collapsed && (
          <span className="text-lg font-semibold text-content-primary">PULSE</span>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        <ul className="flex flex-col gap-0.5">
          {visibleItems.map((item) => {
            const isActive = matchRoute({ to: item.path, fuzzy: true });
            const Icon = item.icon;

            return (
              <li key={item.path}>
                <Link
                  to={item.path}
                  className={`
                    flex items-center gap-3 rounded-button px-3 py-2 text-sm font-medium
                    transition-colors duration-150
                    ${
                      isActive
                        ? 'bg-brand-light text-brand-primary'
                        : 'text-content-secondary hover:bg-surface-tertiary hover:text-content-primary'
                    }
                    ${collapsed ? 'justify-center' : ''}
                  `}
                  title={collapsed ? item.label : undefined}
                >
                  <Icon className="h-5 w-5 shrink-0" />
                  {!collapsed && <span>{item.label}</span>}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Collapse toggle */}
      <div className="border-t border-border-default p-2">
        <button
          onClick={() => setCollapsed((prev) => !prev)}
          className={`
            flex w-full items-center gap-3 rounded-button px-3 py-2 text-sm
            text-content-secondary transition-colors hover:bg-surface-tertiary
            hover:text-content-primary
            ${collapsed ? 'justify-center' : ''}
          `}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-5 w-5 shrink-0" />
          ) : (
            <>
              <PanelLeftClose className="h-5 w-5 shrink-0" />
              <span>Collapse</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
