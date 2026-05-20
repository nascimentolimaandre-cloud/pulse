import { Test, TestingModule } from '@nestjs/testing';
import { ObservabilityAdminController } from './observability-admin.controller';
import { ObservabilityProxyService } from './observability-proxy.service';
import type {
  DatadogValidateResponse,
  CredentialMetadataResponse,
  OwnershipSyncResponse,
  OwnershipRowResponse,
  OwnershipListResponse,
  AliasListResponse,
  AliasResponse,
  AliasBulkImportResponse,
  AliasSuggestionsResponse,
} from '@pulse/shared';

const TENANT_ID = '00000000-0000-0000-0000-000000000001';

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const mockValidateResponse: DatadogValidateResponse = {
  valid: true,
  persisted: true,
  site: 'datadoghq.com',
  key_fingerprint: 'abc123',
  validated_at: '2026-05-20T00:00:00Z',
  message: 'Credential validated and stored.',
};

const mockMetadataResponse: CredentialMetadataResponse = {
  provider: 'datadog',
  site: 'datadoghq.com',
  has_app_key: false,
  validated_at: '2026-05-20T00:00:00Z',
  last_rotated_at: '2026-05-20T00:00:00Z',
  key_fingerprint: 'abc123',
  status: 'validated',
};

const mockSyncResponse: OwnershipSyncResponse = {
  services_seen: 100,
  inferred_with_tag: 80,
  inferred_with_alias: 10,
  inferred_none: 10,
  unchanged: 50,
  duration_ms: 1234,
};

const mockOwnershipRow: OwnershipRowResponse = {
  service_external_id: 'svc-1',
  service_name: 'checkout-api',
  repo_url: 'https://github.com/org/checkout-api',
  inferred_squad_key: 'squad-a',
  inferred_confidence: 'tag',
  override_squad_key: null,
  effective_squad_key: 'squad-a',
  last_inference_at: '2026-05-20T00:00:00Z',
  is_qualified_squad: true,
};

const mockOwnershipList: OwnershipListResponse = {
  services: [mockOwnershipRow],
  coverage_pct: 0.9,
};

const mockAlias: AliasResponse = {
  vendor_team_value: 'dd-team-checkout',
  squad_key: 'squad-a',
  created_at: '2026-05-20T00:00:00Z',
  updated_at: '2026-05-20T00:00:00Z',
};

const mockAliasList: AliasListResponse = {
  aliases: [mockAlias],
  total: 1,
};

const mockBulkImport: AliasBulkImportResponse = {
  inserted: 5,
  updated: 2,
  rejected_invalid_squad: 1,
  rejected_empty: 0,
  total_submitted: 8,
};

const mockSuggestions: AliasSuggestionsResponse = {
  vendor_teams: ['unmapped-team-1', 'unmapped-team-2'],
  total: 2,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ObservabilityAdminController', () => {
  let controller: ObservabilityAdminController;
  let proxy: jest.Mocked<ObservabilityProxyService>;

  beforeEach(async () => {
    const mockProxy = {
      get: jest.fn(),
      post: jest.fn(),
      put: jest.fn(),
      delete: jest.fn(),
    };

    const module: TestingModule = await Test.createTestingModule({
      controllers: [ObservabilityAdminController],
      providers: [
        { provide: ObservabilityProxyService, useValue: mockProxy },
      ],
    }).compile();

    controller = module.get<ObservabilityAdminController>(ObservabilityAdminController);
    proxy = module.get(ObservabilityProxyService) as jest.Mocked<ObservabilityProxyService>;
  });

  // -------------------------------------------------------------------------
  // 1. POST /datadog/validate
  // -------------------------------------------------------------------------

  describe('POST /datadog/validate', () => {
    it('should forward validate request and return response', async () => {
      proxy.post.mockResolvedValue(mockValidateResponse);
      const dto = { api_key: 'abc1234567', site: 'datadoghq.com', persist: true };
      const result = await controller.validateDatadogCredential(TENANT_ID, dto);

      expect(result).toEqual(mockValidateResponse);
      expect(proxy.post).toHaveBeenCalledWith(
        'admin/integrations/datadog/validate',
        TENANT_ID,
        dto,
      );
    });
  });

  // -------------------------------------------------------------------------
  // 2. GET /:provider/metadata
  // -------------------------------------------------------------------------

  describe('GET /:provider/metadata', () => {
    it('should return credential metadata', async () => {
      proxy.get.mockResolvedValue(mockMetadataResponse);
      const result = await controller.getProviderMetadata(TENANT_ID, 'datadog');

      expect(result).toEqual(mockMetadataResponse);
      expect(proxy.get).toHaveBeenCalledWith(
        'admin/integrations/datadog/metadata',
        TENANT_ID,
      );
    });
  });

  // -------------------------------------------------------------------------
  // 3. POST /:provider/ownership/sync
  // -------------------------------------------------------------------------

  describe('POST /:provider/ownership/sync', () => {
    it('should trigger ownership sync', async () => {
      proxy.post.mockResolvedValue(mockSyncResponse);
      const result = await controller.syncOwnership(TENANT_ID, 'datadog');

      expect(result).toEqual(mockSyncResponse);
      expect(proxy.post).toHaveBeenCalledWith(
        'admin/integrations/datadog/ownership/sync',
        TENANT_ID,
      );
    });
  });

  // -------------------------------------------------------------------------
  // 4. PUT /:provider/ownership/:id/override
  // -------------------------------------------------------------------------

  describe('PUT /:provider/ownership/:id/override', () => {
    it('should upsert override', async () => {
      proxy.put.mockResolvedValue(mockOwnershipRow);
      const dto = { squad_key: 'squad-a' };
      const result = await controller.upsertOverride(
        TENANT_ID, 'datadog', 'svc-1', dto,
      );

      expect(result).toEqual(mockOwnershipRow);
      expect(proxy.put).toHaveBeenCalledWith(
        'admin/integrations/datadog/ownership/svc-1/override',
        TENANT_ID,
        dto,
      );
    });

    it('should clear override with null squad_key', async () => {
      const clearedRow = { ...mockOwnershipRow, override_squad_key: null };
      proxy.put.mockResolvedValue(clearedRow);
      const dto = { squad_key: null };
      const result = await controller.upsertOverride(
        TENANT_ID, 'datadog', 'svc-1', dto,
      );

      expect(result.override_squad_key).toBeNull();
    });
  });

  // -------------------------------------------------------------------------
  // 5. GET /:provider/ownership
  // -------------------------------------------------------------------------

  describe('GET /:provider/ownership', () => {
    it('should list ownership map', async () => {
      proxy.get.mockResolvedValue(mockOwnershipList);
      const result = await controller.listOwnership(TENANT_ID, 'datadog');

      expect(result.services).toHaveLength(1);
      expect(result.coverage_pct).toBe(0.9);
      expect(proxy.get).toHaveBeenCalledWith(
        'admin/integrations/datadog/ownership',
        TENANT_ID,
      );
    });
  });

  // -------------------------------------------------------------------------
  // 6. GET /:provider/aliases
  // -------------------------------------------------------------------------

  describe('GET /:provider/aliases', () => {
    it('should list aliases', async () => {
      proxy.get.mockResolvedValue(mockAliasList);
      const result = await controller.listAliases(TENANT_ID, 'datadog');

      expect(result.aliases).toHaveLength(1);
      expect(result.total).toBe(1);
    });
  });

  // -------------------------------------------------------------------------
  // 7. PUT /:provider/aliases/:vendorTeamValue
  // -------------------------------------------------------------------------

  describe('PUT /:provider/aliases/:vendorTeamValue', () => {
    it('should upsert alias', async () => {
      proxy.put.mockResolvedValue(mockAlias);
      const dto = { vendor_team_value: 'dd-team-checkout', squad_key: 'squad-a' };
      const result = await controller.upsertAlias(
        TENANT_ID, 'datadog', 'dd-team-checkout', dto,
      );

      expect(result).toEqual(mockAlias);
      expect(proxy.put).toHaveBeenCalledWith(
        'admin/integrations/datadog/aliases/dd-team-checkout',
        TENANT_ID,
        dto,
      );
    });
  });

  // -------------------------------------------------------------------------
  // 8. DELETE /:provider/aliases/:vendorTeamValue
  // -------------------------------------------------------------------------

  describe('DELETE /:provider/aliases/:vendorTeamValue', () => {
    it('should delete alias and return void', async () => {
      proxy.delete.mockResolvedValue(204);
      await controller.deleteAlias(TENANT_ID, 'datadog', 'dd-team-checkout');

      expect(proxy.delete).toHaveBeenCalledWith(
        'admin/integrations/datadog/aliases/dd-team-checkout',
        TENANT_ID,
      );
    });
  });

  // -------------------------------------------------------------------------
  // 9. POST /:provider/aliases/import
  // -------------------------------------------------------------------------

  describe('POST /:provider/aliases/import', () => {
    it('should bulk import aliases', async () => {
      proxy.post.mockResolvedValue(mockBulkImport);
      const dto = {
        mappings: [
          { vendor_team_value: 'team-a', squad_key: 'squad-a' },
          { vendor_team_value: 'team-b', squad_key: 'squad-b' },
        ],
      };
      const result = await controller.bulkImportAliases(
        TENANT_ID, 'datadog', dto,
      );

      expect(result).toEqual(mockBulkImport);
      expect(proxy.post).toHaveBeenCalledWith(
        'admin/integrations/datadog/aliases/import',
        TENANT_ID,
        dto,
      );
    });
  });

  // -------------------------------------------------------------------------
  // 10. GET /:provider/aliases/suggestions
  // -------------------------------------------------------------------------

  describe('GET /:provider/aliases/suggestions', () => {
    it('should return alias suggestions', async () => {
      proxy.get.mockResolvedValue(mockSuggestions);
      const result = await controller.aliasSuggestions(TENANT_ID, 'datadog');

      expect(result.vendor_teams).toHaveLength(2);
      expect(result.total).toBe(2);
    });
  });

  // -------------------------------------------------------------------------
  // Tenant context forwarding
  // -------------------------------------------------------------------------

  describe('Tenant context', () => {
    it('should forward tenant ID to proxy on every call', async () => {
      const customTenant = '11111111-1111-1111-1111-111111111111';
      proxy.get.mockResolvedValue(mockMetadataResponse);

      await controller.getProviderMetadata(customTenant, 'datadog');

      expect(proxy.get).toHaveBeenCalledWith(
        expect.any(String),
        customTenant,
      );
    });
  });

  // -------------------------------------------------------------------------
  // Provider param encoding
  // -------------------------------------------------------------------------

  describe('Provider param encoding', () => {
    it('should encode provider param in URL', async () => {
      proxy.get.mockResolvedValue(mockMetadataResponse);
      await controller.getProviderMetadata(TENANT_ID, 'new relic');

      expect(proxy.get).toHaveBeenCalledWith(
        'admin/integrations/new%20relic/metadata',
        TENANT_ID,
      );
    });
  });
});
