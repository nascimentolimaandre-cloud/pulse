import { Test, TestingModule } from '@nestjs/testing';
import { BadRequestException } from '@nestjs/common';
import { ObservabilityPublicController } from './observability-public.controller';
import { ObservabilityProxyService } from './observability-proxy.service';
import type { TimelineResponse } from '@pulse/shared';

const TENANT_ID = '00000000-0000-0000-0000-000000000001';

const mockTimeline: TimelineResponse = {
  scope: 'squad',
  squad_key: 'squad-a',
  service: null,
  since: '2026-05-13T00:00:00Z',
  until: '2026-05-20T00:00:00Z',
  buckets: [
    {
      hour_bucket: '2026-05-19T14:00:00Z',
      severity: 1.5,
      samples_count: 12,
      metric: 'error_rate',
      service: null,
    },
  ],
  deploys: [
    {
      deployed_at: '2026-05-19T15:30:00Z',
      repo: 'checkout-api',
      environment: 'production',
      sha: 'abc1234',
      is_failure: false,
      url: 'https://github.com/org/checkout-api/commit/abc1234',
      service: null,
    },
  ],
  services_in_squad: 5,
  has_data: true,
};

describe('ObservabilityPublicController', () => {
  let controller: ObservabilityPublicController;
  let proxy: jest.Mocked<ObservabilityProxyService>;

  beforeEach(async () => {
    const mockProxy = {
      get: jest.fn(),
      post: jest.fn(),
      put: jest.fn(),
      delete: jest.fn(),
    };

    const module: TestingModule = await Test.createTestingModule({
      controllers: [ObservabilityPublicController],
      providers: [
        { provide: ObservabilityProxyService, useValue: mockProxy },
      ],
    }).compile();

    controller = module.get<ObservabilityPublicController>(ObservabilityPublicController);
    proxy = module.get(ObservabilityProxyService) as jest.Mocked<ObservabilityProxyService>;
  });

  // -------------------------------------------------------------------------
  // 11. GET /timeline
  // -------------------------------------------------------------------------

  describe('GET /timeline', () => {
    it('should return timeline for a squad', async () => {
      proxy.get.mockResolvedValue(mockTimeline);
      const result = await controller.getTimeline(TENANT_ID, {
        squad_key: 'squad-a',
      });

      expect(result).toEqual(mockTimeline);
      expect(proxy.get).toHaveBeenCalledWith(
        'obs/timeline',
        TENANT_ID,
        {
          squad_key: 'squad-a',
          service: undefined,
          since: undefined,
          until: undefined,
          provider: undefined,
        },
      );
    });

    it('should return timeline for a single service', async () => {
      const serviceTimeline: TimelineResponse = {
        ...mockTimeline,
        scope: 'service',
        squad_key: null,
        service: 'checkout-api',
      };
      proxy.get.mockResolvedValue(serviceTimeline);
      const result = await controller.getTimeline(TENANT_ID, {
        service: 'checkout-api',
      });

      expect(result.scope).toBe('service');
      expect(result.service).toBe('checkout-api');
    });

    it('should pass since/until/provider params', async () => {
      proxy.get.mockResolvedValue(mockTimeline);
      await controller.getTimeline(TENANT_ID, {
        squad_key: 'squad-a',
        since: '2026-05-01T00:00:00Z',
        until: '2026-05-20T00:00:00Z',
        provider: 'datadog',
      });

      expect(proxy.get).toHaveBeenCalledWith(
        'obs/timeline',
        TENANT_ID,
        {
          squad_key: 'squad-a',
          service: undefined,
          since: '2026-05-01T00:00:00Z',
          until: '2026-05-20T00:00:00Z',
          provider: 'datadog',
        },
      );
    });

    it('should reject when neither squad_key nor service is provided', () => {
      expect(() =>
        controller.getTimeline(TENANT_ID, {}),
      ).toThrow(BadRequestException);
    });

    it('should reject when both squad_key and service are provided', () => {
      expect(() =>
        controller.getTimeline(TENANT_ID, {
          squad_key: 'squad-a',
          service: 'checkout-api',
        }),
      ).toThrow(BadRequestException);
    });
  });

  // -------------------------------------------------------------------------
  // Tenant context
  // -------------------------------------------------------------------------

  describe('Tenant context', () => {
    it('should forward tenant ID in proxy call', async () => {
      const customTenant = '22222222-2222-2222-2222-222222222222';
      proxy.get.mockResolvedValue(mockTimeline);

      await controller.getTimeline(customTenant, { squad_key: 'squad-a' });

      expect(proxy.get).toHaveBeenCalledWith(
        'obs/timeline',
        customTenant,
        expect.any(Object),
      );
    });
  });
});
