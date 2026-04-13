import { useEffect } from 'react';
import { createRoute, Link, Outlet, useMatchRoute, useNavigate } from '@tanstack/react-router';
import { rootRoute } from '../../../__root';
import { DiscoveryStatusBadge } from './_components/discovery-status-badge';
import { useDiscoveryStatusQuery } from '@/hooks/useJiraAdmin';

export const jiraSettingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/settings/integrations/jira',
  component: JiraSettingsLayout,
});

interface TabDef {
  to: string;
  label: string;
}

const TABS: TabDef[] = [
  { to: '/settings/integrations/jira/catalog', label: 'Projetos' },
  { to: '/settings/integrations/jira/config', label: 'Configuracao' },
  { to: '/settings/integrations/jira/audit', label: 'Auditoria' },
];

function JiraSettingsLayout() {
  const matchRoute = useMatchRoute();
  const navigate = useNavigate();
  const { data: discoveryStatus, isLoading: discoveryLoading } = useDiscoveryStatusQuery();

  // If user navigates to /settings/integrations/jira exactly, redirect to catalog tab
  const isExactMatch = matchRoute({ to: '/settings/integrations/jira', fuzzy: false });

  useEffect(() => {
    if (isExactMatch) {
      void navigate({ to: '/settings/integrations/jira/catalog', replace: true });
    }
  }, [isExactMatch, navigate]);

  return (
    <div>
      {/* Header */}
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-content-primary">Jira Integration</h1>
          <p className="mt-1 text-sm text-content-secondary">
            Gerenciamento de projetos Jira, modo de descoberta e auditoria.
          </p>
        </div>
        <DiscoveryStatusBadge status={discoveryStatus} isLoading={discoveryLoading} />
      </div>

      {/* Tab bar */}
      <div className="mb-6 flex gap-1 border-b border-border-default">
        {TABS.map((tab) => {
          const isActive = matchRoute({ to: tab.to, fuzzy: true });
          return (
            <Link
              key={tab.to}
              to={tab.to}
              className={`
                -mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors
                ${
                  isActive
                    ? 'border-brand-primary text-brand-primary'
                    : 'border-transparent text-content-secondary hover:border-border-hover hover:text-content-primary'
                }
              `}
            >
              {tab.label}
            </Link>
          );
        })}
      </div>

      {/* Tab content */}
      <Outlet />
    </div>
  );
}
