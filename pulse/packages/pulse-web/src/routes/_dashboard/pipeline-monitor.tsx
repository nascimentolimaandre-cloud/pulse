import { createRoute } from '@tanstack/react-router';
import { useState } from 'react';
import { Activity, Workflow, Users, Zap } from 'lucide-react';
import { rootRoute } from '../__root';
import { TrustStrip } from '@/components/pipeline/TrustStrip';
import { IntegrationBox } from '@/components/pipeline/IntegrationBox';
import { SourceCard } from '@/components/pipeline/SourceCard';
import { PipelinePhaseView } from '@/components/pipeline/PipelinePhaseView';
import { TeamHealthTable } from '@/components/pipeline/TeamHealthTable';
import { EntityDrawer } from '@/components/pipeline/EntityDrawer';
import { Timeline } from '@/components/pipeline/Timeline';
import { CoveragePanel } from '@/components/pipeline/CoveragePanel';
import { PerScopeJobs } from '@/components/pipeline/PerScopeJobs';
import { usePipelineHealth, usePipelineSources } from '@/hooks/usePipeline';
import type { Source, Entity } from '@/types/pipeline';

type TabId = 'overview' | 'pipeline' | 'teams' | 'jobs';

const TABS: Array<{ id: TabId; label: string; icon: typeof Activity }> = [
  { id: 'overview', label: 'Visao geral', icon: Activity },
  { id: 'pipeline', label: 'Pipeline', icon: Workflow },
  { id: 'teams', label: 'Times', icon: Users },
  { id: 'jobs', label: 'Per-scope', icon: Zap },
];

function EmptyState() {
  return (
    <div className="py-[60px] flex flex-col items-center text-center">
      <h2 className="text-[18px] font-semibold text-content-primary mb-[8px]">
        Conecte sua primeira fonte
      </h2>
      <p className="text-[14px] text-content-secondary mb-[32px] max-w-[440px]">
        Configure uma integracao para comecar a monitorar o pipeline de dados.
      </p>
      <div className="flex gap-[16px] flex-wrap justify-center">
        {[
          { id: 'github', name: 'GitHub', desc: 'Pull requests, reviews, commits' },
          { id: 'jira', name: 'Jira', desc: 'Issues, sprints, changelogs' },
          { id: 'jenkins', name: 'Jenkins', desc: 'Builds, deployments' },
        ].map((s) => (
          <div
            key={s.id}
            className="w-[200px] py-[24px] px-[20px] rounded-card border-2 border-dashed border-border-default bg-surface-primary text-center"
          >
            <div className="text-[14px] font-semibold text-content-primary mb-[4px]">
              {s.name}
            </div>
            <div className="text-[12px] text-content-secondary">{s.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PipelineMonitorPage() {
  const [tab, setTab] = useState<TabId>('overview');
  const [drawer, setDrawer] = useState<{
    source: Source;
    entity: Entity;
  } | null>(null);

  const health = usePipelineHealth();
  const sources = usePipelineSources();

  const hasConnected = sources.data && sources.data.length > 0;

  return (
    <div className="max-w-content mx-auto px-[24px] py-[20px] font-sans">
      {/* Trust strip */}
      <TrustStrip health={health.data} isLoading={health.isLoading} />

      {/* Integration box */}
      <IntegrationBox />

      {/* Empty state */}
      {!sources.isLoading && !hasConnected && <EmptyState />}

      {/* Tabs + content */}
      {hasConnected && (
        <>
          <div className="flex gap-[4px] mb-[18px] border-b-2 border-border-default">
            {TABS.map((t) => {
              const active = tab === t.id;
              return (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`flex items-center gap-[6px] py-[10px] px-[18px] bg-transparent border-none cursor-pointer text-[14px] border-b-2 -mb-[2px] transition-all duration-150
                    ${active
                      ? 'font-semibold text-brand-primary border-brand-primary'
                      : 'font-medium text-content-secondary border-transparent hover:text-content-primary'
                    }
                    focus-visible:ring-2 focus-visible:ring-brand-primary focus-visible:outline-none`}
                >
                  <t.icon size={16} />
                  {t.label}
                </button>
              );
            })}
          </div>

          {/* Overview tab */}
          {tab === 'overview' && (
            <div className="grid grid-cols-1 xl:grid-cols-[1fr_300px] gap-[20px] items-start">
              <div className="flex flex-col gap-[16px]">
                {sources.data?.map((s) => (
                  <SourceCard
                    key={s.id}
                    source={s}
                    onEntity={(src, ent) => setDrawer({ source: src, entity: ent })}
                  />
                ))}
              </div>
              <div className="flex flex-col gap-[16px] xl:sticky xl:top-[20px]">
                <CoveragePanel />
                <Timeline />
              </div>
            </div>
          )}

          {/* Pipeline tab */}
          {tab === 'pipeline' && (
            <div className="grid grid-cols-1 xl:grid-cols-[1fr_300px] gap-[20px] items-start">
              <PipelinePhaseView />
              <Timeline />
            </div>
          )}

          {/* Teams tab */}
          {tab === 'teams' && <TeamHealthTable />}

          {/* Per-scope jobs tab (FDD-OPS-015) */}
          {tab === 'jobs' && <PerScopeJobs />}
        </>
      )}

      {/* Entity drawer */}
      {drawer && (
        <EntityDrawer
          source={drawer.source}
          entity={drawer.entity}
          onClose={() => setDrawer(null)}
        />
      )}
    </div>
  );
}

export const pipelineMonitorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/pipeline-monitor',
  component: PipelineMonitorPage,
});
