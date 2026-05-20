import { Test, TestingModule } from '@nestjs/testing';
import { ConfigService } from '@nestjs/config';
import { BadGatewayException, HttpException } from '@nestjs/common';
import axios from 'axios';
import { ObservabilityProxyService } from './observability-proxy.service';

// Mock axios at module level
jest.mock('axios');
const mockedAxios = axios as jest.Mocked<typeof axios>;

const TENANT_ID = '00000000-0000-0000-0000-000000000001';

/**
 * Helper to mock `axios.isAxiosError` — the real signature uses a type
 * predicate which jest.fn() can't satisfy directly. We cast through
 * `unknown` to avoid TS2322.
 */
function mockIsAxiosError(returnValue: boolean): void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (mockedAxios as any).isAxiosError = returnValue
    ? (payload: unknown) => typeof payload === 'object' && payload !== null && 'isAxiosError' in payload
    : () => false;
}

describe('ObservabilityProxyService', () => {
  let service: ObservabilityProxyService;

  beforeEach(async () => {
    // Reset all mocks between tests
    jest.clearAllMocks();

    // Default: realistic isAxiosError behavior
    mockIsAxiosError(true);

    const module: TestingModule = await Test.createTestingModule({
      providers: [
        ObservabilityProxyService,
        {
          provide: ConfigService,
          useValue: {
            get: jest.fn((key: string, defaultVal?: string) => {
              if (key === 'PULSE_DATA_URL') return 'http://pulse-data:8000';
              if (key === 'INTERNAL_API_TOKEN') return 'test-token';
              return defaultVal;
            }),
          },
        },
      ],
    }).compile();

    service = module.get<ObservabilityProxyService>(ObservabilityProxyService);
  });

  // -------------------------------------------------------------------------
  // GET
  // -------------------------------------------------------------------------

  describe('get()', () => {
    it('should call axios.get with correct URL and headers', async () => {
      const data = { provider: 'datadog', site: 'datadoghq.com' };
      mockedAxios.get.mockResolvedValue({ data });

      const result = await service.get('admin/integrations/datadog/metadata', TENANT_ID);

      expect(result).toEqual(data);
      expect(mockedAxios.get).toHaveBeenCalledWith(
        'http://pulse-data:8000/data/v1/admin/integrations/datadog/metadata',
        {
          headers: {
            'Content-Type': 'application/json',
            'X-Tenant-Id': TENANT_ID,
            'X-Internal-Token': 'test-token',
          },
          params: undefined,
          timeout: 30_000,
        },
      );
    });

    it('should pass query params and strip undefined values', async () => {
      mockedAxios.get.mockResolvedValue({ data: {} });

      await service.get('obs/timeline', TENANT_ID, {
        squad_key: 'squad-a',
        service: undefined,
      });

      expect(mockedAxios.get).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          params: { squad_key: 'squad-a' },
        }),
      );
    });
  });

  // -------------------------------------------------------------------------
  // POST
  // -------------------------------------------------------------------------

  describe('post()', () => {
    it('should call axios.post with correct URL and body', async () => {
      const responseData = { valid: true };
      mockedAxios.post.mockResolvedValue({ data: responseData });

      const body = { api_key: 'test', site: 'datadoghq.com' };
      const result = await service.post(
        'admin/integrations/datadog/validate',
        TENANT_ID,
        body,
      );

      expect(result).toEqual(responseData);
      expect(mockedAxios.post).toHaveBeenCalledWith(
        'http://pulse-data:8000/data/v1/admin/integrations/datadog/validate',
        body,
        expect.objectContaining({
          headers: expect.objectContaining({
            'X-Tenant-Id': TENANT_ID,
          }),
        }),
      );
    });
  });

  // -------------------------------------------------------------------------
  // PUT
  // -------------------------------------------------------------------------

  describe('put()', () => {
    it('should call axios.put with correct URL and body', async () => {
      const responseData = { squad_key: 'squad-a' };
      mockedAxios.put.mockResolvedValue({ data: responseData });

      const body = { squad_key: 'squad-a' };
      const result = await service.put(
        'admin/integrations/datadog/ownership/svc-1/override',
        TENANT_ID,
        body,
      );

      expect(result).toEqual(responseData);
    });
  });

  // -------------------------------------------------------------------------
  // DELETE
  // -------------------------------------------------------------------------

  describe('delete()', () => {
    it('should call axios.delete and return status code', async () => {
      mockedAxios.delete.mockResolvedValue({ status: 204, data: null });

      const result = await service.delete(
        'admin/integrations/datadog/aliases/team-x',
        TENANT_ID,
      );

      expect(result).toBe(204);
    });
  });

  // -------------------------------------------------------------------------
  // Error sanitization (CISO FIND-006)
  // -------------------------------------------------------------------------

  describe('error sanitization', () => {
    it('should return 502 for upstream 500 errors', async () => {
      const axiosError = {
        isAxiosError: true,
        response: {
          status: 500,
          data: { detail: 'Internal server error with stack trace' },
        },
      };
      mockedAxios.get.mockRejectedValue(axiosError);
      mockIsAxiosError(true);

      await expect(
        service.get('admin/integrations/datadog/metadata', TENANT_ID),
      ).rejects.toThrow(BadGatewayException);
    });

    it('should forward safe 404 status with sanitized detail', async () => {
      const axiosError = {
        isAxiosError: true,
        response: {
          status: 404,
          data: { detail: 'No credential configured for provider=datadog' },
        },
      };
      mockedAxios.get.mockRejectedValue(axiosError);
      mockIsAxiosError(true);

      try {
        await service.get('admin/integrations/datadog/metadata', TENANT_ID);
        fail('Should have thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(HttpException);
        const httpErr = err as HttpException;
        expect(httpErr.getStatus()).toBe(404);
        // The detail should be forwarded for safe codes
        const body = httpErr.getResponse() as Record<string, unknown>;
        expect(body['message']).toBe(
          'No credential configured for provider=datadog',
        );
      }
    });

    it('should forward safe 422 status with sanitized detail', async () => {
      const axiosError = {
        isAxiosError: true,
        response: {
          status: 422,
          data: { detail: 'squad_key must not be empty' },
        },
      };
      mockedAxios.put.mockRejectedValue(axiosError);
      mockIsAxiosError(true);

      try {
        await service.put('admin/integrations/datadog/ownership/svc-1/override', TENANT_ID, {});
        fail('Should have thrown');
      } catch (err) {
        const httpErr = err as HttpException;
        expect(httpErr.getStatus()).toBe(422);
      }
    });

    it('should NOT forward detail from non-safe status codes (e.g. 401)', async () => {
      const axiosError = {
        isAxiosError: true,
        response: {
          status: 401,
          data: { detail: 'API key abc123... is invalid for account xyz' },
        },
      };
      mockedAxios.post.mockRejectedValue(axiosError);
      mockIsAxiosError(true);

      try {
        await service.post('admin/integrations/datadog/validate', TENANT_ID, {});
        fail('Should have thrown');
      } catch (err) {
        const httpErr = err as HttpException;
        expect(httpErr.getStatus()).toBe(401);
        const body = httpErr.getResponse() as Record<string, unknown>;
        // Should NOT contain the leaked API key detail
        expect(body['message']).toBe('Upstream authentication failed.');
        expect(body['message']).not.toContain('abc123');
      }
    });

    it('should truncate overly long upstream detail messages', async () => {
      const longDetail = 'A'.repeat(500);
      const axiosError = {
        isAxiosError: true,
        response: {
          status: 400,
          data: { detail: longDetail },
        },
      };
      mockedAxios.post.mockRejectedValue(axiosError);
      mockIsAxiosError(true);

      try {
        await service.post('admin/integrations/datadog/validate', TENANT_ID, {});
        fail('Should have thrown');
      } catch (err) {
        const httpErr = err as HttpException;
        const body = httpErr.getResponse() as Record<string, unknown>;
        const message = body['message'] as string;
        expect(message.length).toBeLessThanOrEqual(260); // 256 + "..."
      }
    });

    it('should return 502 for network errors (no response)', async () => {
      const networkError = {
        isAxiosError: true,
        response: undefined,
        code: 'ECONNREFUSED',
      };
      mockedAxios.get.mockRejectedValue(networkError);
      mockIsAxiosError(true);

      await expect(
        service.get('obs/timeline', TENANT_ID),
      ).rejects.toThrow(BadGatewayException);
    });

    it('should return 502 for non-axios errors', async () => {
      mockedAxios.get.mockRejectedValue(new Error('unexpected'));
      mockIsAxiosError(false);

      await expect(
        service.get('obs/timeline', TENANT_ID),
      ).rejects.toThrow(BadGatewayException);
    });

    it('should never leak pulse-data URL in error messages', async () => {
      const axiosError = {
        isAxiosError: true,
        response: {
          status: 500,
          data: { detail: 'http://pulse-data:8000 connection failed' },
        },
      };
      mockedAxios.get.mockRejectedValue(axiosError);
      mockIsAxiosError(true);

      try {
        await service.get('obs/timeline', TENANT_ID);
        fail('Should have thrown');
      } catch (err) {
        const httpErr = err as HttpException;
        const body = httpErr.getResponse();
        const bodyStr = JSON.stringify(body);
        expect(bodyStr).not.toContain('pulse-data');
        expect(bodyStr).not.toContain('8000');
      }
    });
  });
});
