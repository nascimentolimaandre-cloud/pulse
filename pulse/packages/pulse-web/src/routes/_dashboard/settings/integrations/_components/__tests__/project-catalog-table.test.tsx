import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { JiraProjectCatalogListResponse } from '@pulse/shared';

// Mock the hooks
const mockUseJiraProjectsQuery = vi.fn();
const mockUseBulkProjectActionMutation = vi.fn(() => ({
  mutate: vi.fn(),
  isPending: false,
}));
const mockUseJiraProjectQuery = vi.fn();
const mockUseSmartSuggestionsQuery = vi.fn(() => ({
  data: undefined,
}));

vi.mock('@/hooks/useJiraAdmin', () => ({
  useJiraProjectsQuery: (...args: unknown[]) => mockUseJiraProjectsQuery(...args),
  useBulkProjectActionMutation: () => mockUseBulkProjectActionMutation(),
  useJiraProjectQuery: (...args: unknown[]) => mockUseJiraProjectQuery(...args),
  useSmartSuggestionsQuery: () => mockUseSmartSuggestionsQuery(),
  useProjectActionMutation: () => ({
    mutate: vi.fn(),
    isPending: false,
  }),
}));

// Import after mocks
import { ProjectCatalogTable } from '../project-catalog-table';

function createWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

const MOCK_RESPONSE: JiraProjectCatalogListResponse = {
  items: [
    {
      id: '1',
      tenantId: 't1',
      projectKey: 'PROJ1',
      projectId: '10001',
      name: 'Project One',
      projectType: 'software',
      leadAccountId: null,
      status: 'active',
      activationSource: 'manual',
      issueCount: 150,
      prReferenceCount: 42,
      firstSeenAt: '2026-01-01T00:00:00Z',
      activatedAt: '2026-01-02T00:00:00Z',
      lastSyncAt: '2026-04-12T10:00:00Z',
      lastSyncStatus: 'success',
      consecutiveFailures: 0,
      lastError: null,
      metadata: {},
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-04-12T10:00:00Z',
    },
    {
      id: '2',
      tenantId: 't1',
      projectKey: 'PROJ2',
      projectId: '10002',
      name: 'Project Two',
      projectType: 'software',
      leadAccountId: null,
      status: 'discovered',
      activationSource: null,
      issueCount: 0,
      prReferenceCount: 88,
      firstSeenAt: '2026-04-10T00:00:00Z',
      activatedAt: null,
      lastSyncAt: null,
      lastSyncStatus: null,
      consecutiveFailures: 0,
      lastError: null,
      metadata: {},
      createdAt: '2026-04-10T00:00:00Z',
      updatedAt: '2026-04-10T00:00:00Z',
    },
  ],
  total: 2,
  counts: { discovered: 1, active: 1, paused: 0, blocked: 0, archived: 0 },
};

describe('ProjectCatalogTable', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders loading skeleton while fetching', () => {
    mockUseJiraProjectsQuery.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
    });

    render(<ProjectCatalogTable />, { wrapper: createWrapper() });
    // Skeleton rows render animate-pulse divs
    const skeletons = document.querySelectorAll('.animate-pulse');
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it('renders empty state when no projects', () => {
    mockUseJiraProjectsQuery.mockReturnValue({
      data: { items: [], total: 0, counts: { discovered: 0, active: 0, paused: 0, blocked: 0, archived: 0 } },
      isLoading: false,
      isError: false,
      error: null,
    });

    render(<ProjectCatalogTable />, { wrapper: createWrapper() });
    expect(screen.getByText(/Nenhum projeto descoberto/i)).toBeInTheDocument();
  });

  it('renders error state on API failure', () => {
    mockUseJiraProjectsQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error('Network Error'),
    });

    render(<ProjectCatalogTable />, { wrapper: createWrapper() });
    expect(screen.getByText(/Falha ao carregar projetos/i)).toBeInTheDocument();
    expect(screen.getByText(/Network Error/i)).toBeInTheDocument();
  });

  it('renders project rows with correct data', () => {
    mockUseJiraProjectsQuery.mockReturnValue({
      data: MOCK_RESPONSE,
      isLoading: false,
      isError: false,
      error: null,
    });

    render(<ProjectCatalogTable />, { wrapper: createWrapper() });

    // Text appears in both table cells and side panel/filter chips → use getAllByText
    expect(screen.getAllByText('PROJ1').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Project One').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Ativo').length).toBeGreaterThan(0);

    expect(screen.getAllByText('PROJ2').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Project Two').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Descoberto').length).toBeGreaterThan(0);
  });

  it('renders filter chips with counts', () => {
    mockUseJiraProjectsQuery.mockReturnValue({
      data: MOCK_RESPONSE,
      isLoading: false,
      isError: false,
      error: null,
    });

    render(<ProjectCatalogTable />, { wrapper: createWrapper() });

    expect(screen.getByText(/Todos/)).toBeInTheDocument();
    expect(screen.getByText(/Ativos/)).toBeInTheDocument();
    expect(screen.getByText(/Descobertos/)).toBeInTheDocument();
  });
});
