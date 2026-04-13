import { createRoute } from '@tanstack/react-router';
import { jiraSettingsRoute } from './jira';
import { SmartSuggestionsBanner } from './_components/smart-suggestions-banner';
import { ProjectCatalogTable } from './_components/project-catalog-table';
import { DiscoveryTriggerButton } from './_components/discovery-trigger-button';

export const jiraCatalogRoute = createRoute({
  getParentRoute: () => jiraSettingsRoute,
  path: '/catalog',
  component: JiraCatalogTab,
});

function JiraCatalogTab() {
  return (
    <div>
      {/* Discovery trigger at top-right */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-base font-semibold text-content-primary">Catalogo de Projetos</h2>
        <DiscoveryTriggerButton />
      </div>

      {/* Smart suggestions banner */}
      <SmartSuggestionsBanner />

      {/* Project catalog table */}
      <ProjectCatalogTable />
    </div>
  );
}
