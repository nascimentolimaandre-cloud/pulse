import { Test, TestingModule } from '@nestjs/testing';
import { JiraAdminController } from './jira-admin.controller';
import { JiraAdminService } from './jira-admin.service';
import type { CurrentUserPayload } from '@/common/decorators/current-user.decorator';
import type {
  TenantJiraConfig,
  JiraProjectCatalogEntry,
  JiraProjectCatalogListResponse,
  JiraDiscoveryStatusResponse,
  JiraAuditListResponse,
  JiraSmartSuggestionsResponse,
} from '@pulse/shared';

const TENANT_ID = '00000000-0000-0000-0000-000000000001';
const USER: CurrentUserPayload = {
  id: '00000000-0000-0000-0000-000000000099',
  email: 'admin@test.com',
  name: 'Test Admin',
  orgId: TENANT_ID,
  role: 'admin',
};

const mockConfig: TenantJiraConfig = {
  tenantId: TENANT_ID,
  mode: 'smart',
  discoveryEnabled: true,
  discoveryScheduleCron: '0 3 * * *',
  maxActiveProjects: 100,
  maxIssuesPerHour: 10000,
  smartPrScanDays: 90,
  smartMinPrReferences: 5,
  lastDiscoveryAt: null,
  lastDiscoveryStatus: null,
  lastDiscoveryError: null,
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
};

const mockCatalogEntry: JiraProjectCatalogEntry = {
  id: 'cat-1',
  tenantId: TENANT_ID,
  projectKey: 'PULSE',
  projectId: '10001',
  name: 'PULSE Project',
  projectType: 'software',
  leadAccountId: null,
  status: 'discovered',
  activationSource: null,
  issueCount: 42,
  prReferenceCount: 10,
  firstSeenAt: '2026-01-01T00:00:00Z',
  activatedAt: null,
  lastSyncAt: null,
  lastSyncStatus: null,
  consecutiveFailures: 0,
  lastError: null,
  metadata: {},
  createdAt: '2026-01-01T00:00:00Z',
  updatedAt: '2026-01-01T00:00:00Z',
};

const mockListResponse: JiraProjectCatalogListResponse = {
  items: [mockCatalogEntry],
  total: 1,
  counts: { discovered: 1, active: 0, paused: 0, blocked: 0, archived: 0 },
};

const mockDiscoveryStatus: JiraDiscoveryStatusResponse = {
  inFlight: false,
  currentRunId: null,
  lastRun: null,
  tenantConfig: {
    mode: 'smart',
    discoveryEnabled: true,
    discoveryScheduleCron: '0 3 * * *',
    lastDiscoveryAt: null,
    lastDiscoveryStatus: null,
  },
};

const mockAuditResponse: JiraAuditListResponse = {
  items: [],
  total: 0,
};

const mockSuggestions: JiraSmartSuggestionsResponse = {
  items: [
    {
      projectKey: 'CKP',
      prReferenceCount: 524,
      suggestedAction: 'activate',
      reason: 'Referenced in 524 PRs',
    },
  ],
  thresholdPrReferences: 5,
};

describe('JiraAdminController', () => {
  let controller: JiraAdminController;
  let service: jest.Mocked<JiraAdminService>;

  beforeEach(async () => {
    const mockService = {
      getConfig: jest.fn(),
      updateConfig: jest.fn(),
      listProjects: jest.fn(),
      getProject: jest.fn(),
      changeProjectStatus: jest.fn(),
      triggerDiscovery: jest.fn(),
      getDiscoveryStatus: jest.fn(),
      listAudit: jest.fn(),
      getSmartSuggestions: jest.fn(),
    };

    const module: TestingModule = await Test.createTestingModule({
      controllers: [JiraAdminController],
      providers: [
        { provide: JiraAdminService, useValue: mockService },
      ],
    }).compile();

    controller = module.get<JiraAdminController>(JiraAdminController);
    service = module.get(JiraAdminService) as jest.Mocked<JiraAdminService>;
  });

  describe('GET /config', () => {
    it('should return tenant config', async () => {
      service.getConfig.mockResolvedValue(mockConfig);
      const result = await controller.getConfig(TENANT_ID);
      expect(result).toEqual(mockConfig);
      expect(service.getConfig).toHaveBeenCalledWith(TENANT_ID);
    });
  });

  describe('PUT /config', () => {
    it('should update config and pass actor id', async () => {
      const updated = { ...mockConfig, mode: 'auto' as const };
      service.updateConfig.mockResolvedValue(updated);
      const dto = { mode: 'auto' as const };
      const result = await controller.updateConfig(TENANT_ID, USER, dto);
      expect(result.mode).toBe('auto');
      expect(service.updateConfig).toHaveBeenCalledWith(
        TENANT_ID, dto, USER.id,
      );
    });
  });

  describe('GET /projects', () => {
    it('should return project catalog list', async () => {
      service.listProjects.mockResolvedValue(mockListResponse);
      const result = await controller.listProjects(TENANT_ID, {});
      expect(result.items).toHaveLength(1);
      expect(result.total).toBe(1);
      expect(result.counts.discovered).toBe(1);
    });

    it('should pass query filters to service', async () => {
      service.listProjects.mockResolvedValue(mockListResponse);
      const query = { status: ['active'], search: 'PULSE', limit: 10, offset: 0 };
      await controller.listProjects(TENANT_ID, query);
      expect(service.listProjects).toHaveBeenCalledWith(TENANT_ID, query);
    });
  });

  describe('GET /projects/:key', () => {
    it('should return single project', async () => {
      service.getProject.mockResolvedValue(mockCatalogEntry);
      const result = await controller.getProject(TENANT_ID, 'PULSE');
      expect(result.projectKey).toBe('PULSE');
    });
  });

  describe('POST /projects/:key/activate', () => {
    it('should activate a project', async () => {
      const activated = { ...mockCatalogEntry, status: 'active' as const };
      service.changeProjectStatus.mockResolvedValue(activated);
      const result = await controller.activateProject(
        TENANT_ID, USER, 'PULSE', { reason: 'Need this data' },
      );
      expect(result.status).toBe('active');
      expect(service.changeProjectStatus).toHaveBeenCalledWith(
        TENANT_ID, 'PULSE', 'activate', { reason: 'Need this data' }, USER.id,
      );
    });
  });

  describe('POST /projects/:key/pause', () => {
    it('should pause a project', async () => {
      const paused = { ...mockCatalogEntry, status: 'paused' as const };
      service.changeProjectStatus.mockResolvedValue(paused);
      const result = await controller.pauseProject(
        TENANT_ID, USER, 'PULSE', {},
      );
      expect(result.status).toBe('paused');
      expect(service.changeProjectStatus).toHaveBeenCalledWith(
        TENANT_ID, 'PULSE', 'pause', {}, USER.id,
      );
    });
  });

  describe('POST /projects/:key/block', () => {
    it('should block a project', async () => {
      const blocked = { ...mockCatalogEntry, status: 'blocked' as const };
      service.changeProjectStatus.mockResolvedValue(blocked);
      const result = await controller.blockProject(
        TENANT_ID, USER, 'PULSE', { reason: 'HR project' },
      );
      expect(result.status).toBe('blocked');
    });
  });

  describe('POST /projects/:key/resume', () => {
    it('should resume a project', async () => {
      const resumed = { ...mockCatalogEntry, status: 'active' as const };
      service.changeProjectStatus.mockResolvedValue(resumed);
      const result = await controller.resumeProject(
        TENANT_ID, USER, 'PULSE', {},
      );
      expect(result.status).toBe('active');
    });
  });

  describe('POST /discovery/trigger', () => {
    it('should return runId', async () => {
      service.triggerDiscovery.mockResolvedValue({ runId: 'run-123' });
      const result = await controller.triggerDiscovery(TENANT_ID);
      expect(result.runId).toBe('run-123');
    });
  });

  describe('GET /discovery/status', () => {
    it('should return discovery status', async () => {
      service.getDiscoveryStatus.mockResolvedValue(mockDiscoveryStatus);
      const result = await controller.getDiscoveryStatus(TENANT_ID);
      expect(result.inFlight).toBe(false);
      expect(result.tenantConfig.mode).toBe('smart');
    });
  });

  describe('GET /audit', () => {
    it('should return audit list', async () => {
      service.listAudit.mockResolvedValue(mockAuditResponse);
      const result = await controller.listAudit(TENANT_ID, {});
      expect(result.items).toHaveLength(0);
      expect(result.total).toBe(0);
    });
  });

  describe('GET /smart-suggestions', () => {
    it('should return suggestions', async () => {
      service.getSmartSuggestions.mockResolvedValue(mockSuggestions);
      const result = await controller.getSmartSuggestions(TENANT_ID);
      expect(result.items).toHaveLength(1);
      expect(result.items[0].projectKey).toBe('CKP');
      expect(result.thresholdPrReferences).toBe(5);
    });
  });
});
