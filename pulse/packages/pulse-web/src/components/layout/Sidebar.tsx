import { useState } from 'react';
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
} from 'lucide-react';

interface NavItem {
  label: string;
  path: string;
  icon: React.ComponentType<{ className?: string }>;
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Home', path: '/', icon: Home },
  { label: 'DORA', path: '/metrics/dora', icon: Activity },
  { label: 'Cycle Time', path: '/metrics/cycle-time', icon: Clock },
  { label: 'Throughput', path: '/metrics/throughput', icon: BarChart3 },
  { label: 'Lean & Flow', path: '/metrics/lean', icon: Workflow },
  { label: 'Sprints', path: '/metrics/sprints', icon: Zap },
  { label: 'Open PRs', path: '/prs', icon: GitPullRequest },
  { label: 'Integrations', path: '/integrations', icon: Cable },
  { label: 'Pipeline', path: '/pipeline-monitor', icon: Activity },
];

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const matchRoute = useMatchRoute();

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
          {NAV_ITEMS.map((item) => {
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
