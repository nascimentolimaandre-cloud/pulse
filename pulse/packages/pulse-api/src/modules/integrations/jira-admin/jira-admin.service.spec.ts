import { Test, TestingModule } from '@nestjs/testing';
import { ConfigService } from '@nestjs/config';
import { DataSource, QueryRunner } from 'typeorm';
import { NotFoundException, BadRequestException } from '@nestjs/common';
import { JiraAdminService } from './jira-admin.service';

// ---------------------------------------------------------------------------
// Mock QueryRunner
// ---------------------------------------------------------------------------

function createMockQueryRunner(queryFn: jest.Mock): Partial<QueryRunner> {
  return {
    connect: jest.fn(),
    startTransaction: jest.fn(),
    commitTransaction: jest.fn(),
    rollbackTransaction: jest.fn(),
    release: jest.fn(),
    query: queryFn,
  };
}

const TENANT_ID = '00000000-0000-0000-0000-000000000001';
const ACTOR_ID = '00000000-0000-0000-0000-000000000099';

const dbConfigRow = {
  tenant_id: TENANT_ID,
  mode: 'smart',
  discovery_enabled: true,
  discovery_schedule_cron: '0 3 * * *',
  max_active_projects: 100,
  max_issues_per_hour: 10000,
  smart_pr_scan_days: 90,
  smart_min_pr_references: 5,
  last_discovery_at: null,
  last_discovery_status: null,
  last_discovery_error: null,
  created_at: '2026-01-01T00:00:00.000Z',
  updated_at: '2026-01-01T00:00:00.000Z',
};

const dbCatalogRow = {
  id: 'cat-1',
  tenant_id: TENANT_ID,
  project_key: 'PULSE',
  project_id: '10001',
  name: 'PULSE Project',
  project_type: 'software',
  lead_account_id: null,
  status: 'discovered',
  activation_source: null,
  issue_count: 42,
  pr_reference_count: 10,
  first_seen_at: '2026-01-01T00:00:00.000Z',
  activated_at: null,
  last_sync_at: null,
  last_sync_status: null,
  consecutive_failures: 0,
  last_error: null,
  metadata: {},
  created_at: '2026-01-01T00:00:00.000Z',
  updated_at: '2026-01-01T00:00:00.000Z',
};

describe('JiraAdminService', () => {
  let service: JiraAdminService;
  let queryFn: jest.Mock;
  let mockDataSource: Partial<DataSource>;

  beforeEach(async () => {
    queryFn = jest.fn();
    const mockQr = createMockQueryRunner(queryFn);
    mockDataSource = {
      createQueryRunner: jest.fn().mockReturnValue(mockQr),
    };

    const module: TestingModule = await Test.createTestingModule({
      providers: [
        JiraAdminService,
        { provide: DataSource, useValue: mockDataSource },
        {
          provide: ConfigService,
          useValue: {
            get: jest.fn((key: string, defaultVal?: string) => {
              const map: Record<string, string> = {
                PULSE_DATA_URL: 'http://localhost:8001',
                INTERNAL_API_TOKEN: 'test-token',
              };
              return map[key] ?? defaultVal ?? '';
            }),
          },
        },
      ],
    }).compile();

    service = module.get<JiraAdminService>(JiraAdminService);
  });

  // -------------------------------------------------------------------------
  // getConfig
  // -------------------------------------------------------------------------

  describe('getConfig', () => {
    it('should return mapped config', async () => {
      // SET LOCAL + SELECT
      queryFn
        .mockResolvedValueOnce(undefined) // SET LOCAL
        .mockResolvedValueOnce([dbConfigRow]); // SELECT

      const result = await service.getConfig(TENANT_ID);
      expect(result.tenantId).toBe(TENANT_ID);
      expect(result.mode).toBe('smart');
      expect(result.maxActiveProjects).toBe(100);
    });

    it('should throw NotFoundException if no config', async () => {
      queryFn
        .mockResolvedValueOnce(undefined)
        .mockResolvedValueOnce([]);

      await expect(service.getConfig(TENANT_ID)).rejects.toThrow(
        NotFoundException,
      );
    });
  });

  // -------------------------------------------------------------------------
  // updateConfig
  // -------------------------------------------------------------------------

  describe('updateConfig', () => {
    it('should update mode and write audit entry', async () => {
      const updatedRow = { ...dbConfigRow, mode: 'auto' };
      queryFn
        .mockResolvedValueOnce(undefined) // SET LOCAL
        .mockResolvedValueOnce([dbConfigRow]) // SELECT current
        .mockResolvedValueOnce([updatedRow]) // UPDATE RETURNING
        .mockResolvedValueOnce(undefined); // INSERT audit

      const result = await service.updateConfig(
        TENANT_ID,
        { mode: 'auto' },
        ACTOR_ID,
      );
      expect(result.mode).toBe('auto');

      // Verify audit INSERT was called (4th query call)
      const auditCall = queryFn.mock.calls[3];
      expect(auditCall[0]).toContain('INSERT INTO jira_discovery_audit');
      expect(auditCall[1]).toContain(ACTOR_ID);
    });

    it('should return unchanged config if no fields provided', async () => {
      queryFn
        .mockResolvedValueOnce(undefined)
        .mockResolvedValueOnce([dbConfigRow]);

      const result = await service.updateConfig(TENANT_ID, {}, ACTOR_ID);
      expect(result.mode).toBe('smart');
      // No UPDATE or INSERT should have been called
      expect(queryFn).toHaveBeenCalledTimes(2);
    });
  });

  // -------------------------------------------------------------------------
  // listProjects
  // -------------------------------------------------------------------------

  describe('listProjects', () => {
    it('should return items with counts', async () => {
      queryFn
        .mockResolvedValueOnce(undefined) // SET LOCAL
        .mockResolvedValueOnce([dbCatalogRow]) // SELECT items
        .mockResolvedValueOnce([{ total: 1 }]) // COUNT
        .mockResolvedValueOnce([ // counts by status
          { status: 'discovered', count: 1 },
        ]);

      const result = await service.listProjects(TENANT_ID, {});
      expect(result.items).toHaveLength(1);
      expect(result.total).toBe(1);
      expect(result.counts.discovered).toBe(1);
      expect(result.counts.active).toBe(0);
    });

    it('should apply status and search filters', async () => {
      queryFn
        .mockResolvedValueOnce(undefined)
        .mockResolvedValueOnce([])
        .mockResolvedValueOnce([{ total: 0 }])
        .mockResolvedValueOnce([]);

      await service.listProjects(TENANT_ID, {
        status: ['active'],
        search: 'PULSE',
      });

      const selectCall = queryFn.mock.calls[1][0] as string;
      expect(selectCall).toContain('status = ANY');
      expect(selectCall).toContain('ILIKE');
    });
  });

  // -------------------------------------------------------------------------
  // getProject
  // -------------------------------------------------------------------------

  describe('getProject', () => {
    it('should return a single project', async () => {
      queryFn
        .mockResolvedValueOnce(undefined)
        .mockResolvedValueOnce([dbCatalogRow]);

      const result = await service.getProject(TENANT_ID, 'PULSE');
      expect(result.projectKey).toBe('PULSE');
    });

    it('should throw NotFoundException for missing project', async () => {
      queryFn
        .mockResolvedValueOnce(undefined)
        .mockResolvedValueOnce([]);

      await expect(
        service.getProject(TENANT_ID, 'NOPE'),
      ).rejects.toThrow(NotFoundException);
    });
  });

  // -------------------------------------------------------------------------
  // changeProjectStatus
  // -------------------------------------------------------------------------

  describe('changeProjectStatus', () => {
    it('should activate a discovered project', async () => {
      const activatedRow = { ...dbCatalogRow, status: 'active' };
      queryFn
        .mockResolvedValueOnce(undefined) // SET LOCAL
        .mockResolvedValueOnce([dbCatalogRow]) // SELECT current
        .mockResolvedValueOnce([activatedRow]) // UPDATE RETURNING
        .mockResolvedValueOnce(undefined); // INSERT audit

      const result = await service.changeProjectStatus(
        TENANT_ID, 'PULSE', 'activate', { reason: 'Need it' }, ACTOR_ID,
      );
      expect(result.status).toBe('active');
    });

    it('should reject invalid transition', async () => {
      // Try to pause a discovered project (not allowed)
      queryFn
        .mockResolvedValueOnce(undefined) // SET LOCAL
        .mockResolvedValueOnce([dbCatalogRow]); // status=discovered

      await expect(
        service.changeProjectStatus(
          TENANT_ID, 'PULSE', 'pause', {}, ACTOR_ID,
        ),
      ).rejects.toThrow(BadRequestException);
    });

    it('should reject unknown action', async () => {
      await expect(
        service.changeProjectStatus(
          TENANT_ID, 'PULSE', 'nuke', {}, ACTOR_ID,
        ),
      ).rejects.toThrow(BadRequestException);
    });

    it('should write audit entry with reason', async () => {
      const blockedRow = { ...dbCatalogRow, status: 'blocked' };
      queryFn
        .mockResolvedValueOnce(undefined)
        .mockResolvedValueOnce([dbCatalogRow])
        .mockResolvedValueOnce([blockedRow])
        .mockResolvedValueOnce(undefined);

      await service.changeProjectStatus(
        TENANT_ID, 'PULSE', 'block', { reason: 'HR project' }, ACTOR_ID,
      );

      const auditCall = queryFn.mock.calls[3];
      expect(auditCall[1]).toContain('HR project');
    });
  });

  // -------------------------------------------------------------------------
  // triggerDiscovery (HTTP proxy)
  // -------------------------------------------------------------------------

  describe('triggerDiscovery', () => {
    it('should call pulse-data and return runId', async () => {
      // Mock axios at module level
      const axios = await import('axios');
      jest.spyOn(axios.default, 'post').mockResolvedValueOnce({
        data: { run_id: 'run-abc' },
      });

      const result = await service.triggerDiscovery(TENANT_ID);
      expect(result.runId).toBe('run-abc');
    });
  });

  // -------------------------------------------------------------------------
  // getDiscoveryStatus
  // -------------------------------------------------------------------------

  describe('getDiscoveryStatus', () => {
    it('should return status with no last run', async () => {
      queryFn
        .mockResolvedValueOnce(undefined) // SET LOCAL
        .mockResolvedValueOnce([ // config
          {
            mode: 'smart',
            discovery_enabled: true,
            discovery_schedule_cron: '0 3 * * *',
            last_discovery_at: null,
            last_discovery_status: null,
          },
        ])
        .mockResolvedValueOnce([]); // no audit rows

      const result = await service.getDiscoveryStatus(TENANT_ID);
      expect(result.inFlight).toBe(false);
      expect(result.lastRun).toBeNull();
      expect(result.tenantConfig.mode).toBe('smart');
    });
  });

  // -------------------------------------------------------------------------
  // listAudit
  // -------------------------------------------------------------------------

  describe('listAudit', () => {
    it('should return empty list', async () => {
      queryFn
        .mockResolvedValueOnce(undefined) // SET LOCAL
        .mockResolvedValueOnce([]) // items
        .mockResolvedValueOnce([{ total: 0 }]); // count

      const result = await service.listAudit(TENANT_ID, {});
      expect(result.items).toHaveLength(0);
      expect(result.total).toBe(0);
    });
  });

  // -------------------------------------------------------------------------
  // getSmartSuggestions
  // -------------------------------------------------------------------------

  describe('getSmartSuggestions', () => {
    it('should return suggestions above threshold', async () => {
      queryFn
        .mockResolvedValueOnce(undefined) // SET LOCAL
        .mockResolvedValueOnce([{ smart_min_pr_references: 5 }]) // config
        .mockResolvedValueOnce([ // catalog rows
          { project_key: 'CKP', pr_reference_count: 524 },
        ]);

      const result = await service.getSmartSuggestions(TENANT_ID);
      expect(result.items).toHaveLength(1);
      expect(result.items[0].projectKey).toBe('CKP');
      expect(result.thresholdPrReferences).toBe(5);
    });
  });
});
