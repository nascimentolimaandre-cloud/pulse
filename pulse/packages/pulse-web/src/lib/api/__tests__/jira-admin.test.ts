import { describe, it, expect, vi, beforeEach } from 'vitest';
import type {
  TenantJiraConfig,
  JiraProjectCatalogListResponse,
  JiraDiscoveryStatusResponse,
} from '@pulse/shared';

// Mock axios via the client module
const mockGet = vi.fn();
const mockPut = vi.fn();
const mockPost = vi.fn();

vi.mock('../client', () => ({
  apiClient: {
    get: (...args: unknown[]) => mockGet(...args),
    put: (...args: unknown[]) => mockPut(...args),
    post: (...args: unknown[]) => mockPost(...args),
  },
}));

// Import after mocking
import {
  getJiraConfig,
  updateJiraConfig,
  listJiraProjects,
  activateProject,
  triggerDiscovery,
  getDiscoveryStatus,
  getSmartSuggestions,
  listAudit,
} from '../jira-admin';

const BASE = '/v1/admin/integrations/jira';

const MOCK_CONFIG: TenantJiraConfig = {
  tenantId: 't1',
  mode: 'allowlist',
  discoveryEnabled: true,
  discoveryScheduleCron: '0 3 * * *',
  maxActiveProjects: 100,
  maxIssuesPerHour: 5000,
  smartPrScanDays: 90,
  smartMinPrReferences: 5,
  lastDiscoveryAt: null,
  lastDiscoveryStatus: null,
  lastDiscoveryError: null,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
};

describe('jira-admin API client', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('getJiraConfig calls GET /config and returns data', async () => {
    mockGet.mockResolvedValue({ data: MOCK_CONFIG });

    const result = await getJiraConfig();
    expect(mockGet).toHaveBeenCalledWith(`${BASE}/config`);
    expect(result).toEqual(MOCK_CONFIG);
  });

  it('updateJiraConfig calls PUT /config with input', async () => {
    const updated = { ...MOCK_CONFIG, mode: 'smart' as const };
    mockPut.mockResolvedValue({ data: updated });

    const result = await updateJiraConfig({ mode: 'smart' });
    expect(mockPut).toHaveBeenCalledWith(`${BASE}/config`, { mode: 'smart' });
    expect(result.mode).toBe('smart');
  });

  it('listJiraProjects sends correct query params', async () => {
    const mockResponse: JiraProjectCatalogListResponse = {
      items: [],
      total: 0,
      counts: { discovered: 0, active: 0, paused: 0, blocked: 0, archived: 0 },
    };
    mockGet.mockResolvedValue({ data: mockResponse });

    await listJiraProjects({ status: 'active', search: 'PROJ', limit: 10, offset: 0 });
    expect(mockGet).toHaveBeenCalledWith(`${BASE}/projects`, {
      params: {
        status: 'active',
        search: 'PROJ',
        limit: '10',
        offset: '0',
      },
    });
  });

  it('listJiraProjects joins array status values', async () => {
    mockGet.mockResolvedValue({
      data: { items: [], total: 0, counts: { discovered: 0, active: 0, paused: 0, blocked: 0, archived: 0 } },
    });

    await listJiraProjects({ status: ['active', 'paused'] });
    expect(mockGet).toHaveBeenCalledWith(`${BASE}/projects`, {
      params: { status: 'active,paused' },
    });
  });

  it('activateProject calls POST /:key/activate', async () => {
    mockPost.mockResolvedValue({ data: { projectKey: 'PROJ1', status: 'active' } });

    const result = await activateProject('PROJ1', { reason: 'testing' });
    expect(mockPost).toHaveBeenCalledWith(`${BASE}/projects/PROJ1/activate`, {
      reason: 'testing',
    });
    expect(result.status).toBe('active');
  });

  it('triggerDiscovery calls POST /discovery/trigger', async () => {
    const mockStatus: JiraDiscoveryStatusResponse = {
      inFlight: true,
      currentRunId: 'run-1',
      lastRun: null,
      tenantConfig: {
        mode: 'allowlist',
        discoveryEnabled: true,
        discoveryScheduleCron: '0 3 * * *',
        lastDiscoveryAt: null,
        lastDiscoveryStatus: null,
      },
    };
    mockPost.mockResolvedValue({ data: mockStatus });

    const result = await triggerDiscovery();
    expect(mockPost).toHaveBeenCalledWith(`${BASE}/discovery/trigger`);
    expect(result.inFlight).toBe(true);
  });

  it('getDiscoveryStatus calls GET /discovery/status', async () => {
    mockGet.mockResolvedValue({ data: { inFlight: false } });

    await getDiscoveryStatus();
    expect(mockGet).toHaveBeenCalledWith(`${BASE}/discovery/status`);
  });

  it('getSmartSuggestions calls GET /smart-suggestions', async () => {
    mockGet.mockResolvedValue({ data: { items: [], thresholdPrReferences: 5 } });

    const result = await getSmartSuggestions();
    expect(mockGet).toHaveBeenCalledWith(`${BASE}/smart-suggestions`);
    expect(result.items).toEqual([]);
  });

  it('listAudit sends correct query params', async () => {
    mockGet.mockResolvedValue({ data: { items: [], total: 0 } });

    await listAudit({ eventType: 'mode_changed', projectKey: 'PROJ', limit: 25, offset: 0 });
    expect(mockGet).toHaveBeenCalledWith(`${BASE}/audit`, {
      params: {
        event_type: 'mode_changed',
        project_key: 'PROJ',
        limit: '25',
        offset: '0',
      },
    });
  });
});
