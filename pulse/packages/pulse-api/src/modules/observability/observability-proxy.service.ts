import {
  Injectable,
  Logger,
  BadGatewayException,
  HttpException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import axios, { AxiosError } from 'axios';

/**
 * HTTP proxy service for observability endpoints.
 *
 * Forwards requests to pulse-data (FastAPI :8000) and returns responses.
 * NEVER leaks pulse-data internals (stack traces, internal URLs) in
 * error responses. Error sanitization follows CISO FIND-006 guidance.
 */
@Injectable()
export class ObservabilityProxyService {
  private readonly logger = new Logger(ObservabilityProxyService.name);
  private readonly baseUrl: string;

  constructor(private readonly configService: ConfigService) {
    this.baseUrl = this.configService.get<string>(
      'PULSE_DATA_URL',
      'http://localhost:8000',
    );
  }

  // ---------------------------------------------------------------------------
  // Generic proxy helpers
  // ---------------------------------------------------------------------------

  /**
   * Forward a GET request to pulse-data.
   *
   * @param path — relative path under `/data/v1/` (e.g. `admin/integrations/datadog/metadata`)
   * @param tenantId — tenant UUID forwarded via X-Tenant-Id header
   * @param params — optional query parameters
   */
  async get<T>(
    path: string,
    tenantId: string,
    params?: Record<string, string | undefined>,
  ): Promise<T> {
    const url = `${this.baseUrl}/data/v1/${path}`;
    try {
      const response = await axios.get<T>(url, {
        headers: this.buildHeaders(tenantId),
        params: this.cleanParams(params),
        timeout: 30_000,
      });
      return response.data;
    } catch (err) {
      throw this.sanitizeError(err, 'GET', path);
    }
  }

  /**
   * Forward a POST request to pulse-data.
   */
  async post<T>(
    path: string,
    tenantId: string,
    body?: unknown,
  ): Promise<T> {
    const url = `${this.baseUrl}/data/v1/${path}`;
    try {
      const response = await axios.post<T>(url, body ?? {}, {
        headers: this.buildHeaders(tenantId),
        timeout: 30_000,
      });
      return response.data;
    } catch (err) {
      throw this.sanitizeError(err, 'POST', path);
    }
  }

  /**
   * Forward a PUT request to pulse-data.
   */
  async put<T>(
    path: string,
    tenantId: string,
    body?: unknown,
  ): Promise<T> {
    const url = `${this.baseUrl}/data/v1/${path}`;
    try {
      const response = await axios.put<T>(url, body ?? {}, {
        headers: this.buildHeaders(tenantId),
        timeout: 30_000,
      });
      return response.data;
    } catch (err) {
      throw this.sanitizeError(err, 'PUT', path);
    }
  }

  /**
   * Forward a DELETE request to pulse-data.
   * Returns the HTTP status code (for 204 No Content).
   */
  async delete(
    path: string,
    tenantId: string,
  ): Promise<number> {
    const url = `${this.baseUrl}/data/v1/${path}`;
    try {
      const response = await axios.delete(url, {
        headers: this.buildHeaders(tenantId),
        timeout: 30_000,
      });
      return response.status;
    } catch (err) {
      throw this.sanitizeError(err, 'DELETE', path);
    }
  }

  // ---------------------------------------------------------------------------
  // Internal helpers
  // ---------------------------------------------------------------------------

  private buildHeaders(tenantId: string): Record<string, string> {
    const token = this.configService.get<string>('INTERNAL_API_TOKEN', '');
    return {
      'Content-Type': 'application/json',
      'X-Tenant-Id': tenantId,
      ...(token ? { 'X-Internal-Token': token } : {}),
    };
  }

  /**
   * Strip undefined values from query params so axios doesn't send
   * `?squad_key=undefined`.
   */
  private cleanParams(
    params?: Record<string, string | undefined>,
  ): Record<string, string> | undefined {
    if (!params) return undefined;
    const cleaned: Record<string, string> = {};
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) {
        cleaned[k] = v;
      }
    }
    return Object.keys(cleaned).length > 0 ? cleaned : undefined;
  }

  /**
   * Sanitize errors from pulse-data so we never leak internals.
   *
   * - 4xx from pulse-data: forward the status code with a safe detail
   *   (CISO FIND-006: NEVER forward raw `detail` from upstream — it may
   *   contain exception text). We forward the status code and, for known
   *   safe codes (400, 404, 409, 422), a generic message.
   * - 5xx from pulse-data: return 502 Bad Gateway with an opaque message.
   * - Network errors: return 502 Bad Gateway.
   */
  private sanitizeError(
    err: unknown,
    method: string,
    path: string,
  ): HttpException {
    if (axios.isAxiosError(err)) {
      const axiosErr = err as AxiosError<{ detail?: string }>;
      const status = axiosErr.response?.status;
      const upstreamDetail = axiosErr.response?.data?.detail;

      this.logger.warn(
        'Observability proxy error: %s %s -> upstream status=%s',
        method,
        path,
        status ?? 'NETWORK_ERROR',
      );

      if (status && status >= 400 && status < 500) {
        // Forward safe client errors with their original status code.
        // CISO FIND-006: we ONLY forward the detail string for known
        // application-level error codes where the upstream detail is
        // controlled (e.g. "No credential configured for provider=X").
        // For anything potentially leaky (DatadogConnectorError, etc.)
        // we use a generic message.
        const safeDetail = this.safeClientDetail(status, upstreamDetail);
        throw new HttpException(
          { statusCode: status, message: safeDetail },
          status,
        );
      }

      // 5xx or network error -> 502
      throw new BadGatewayException(
        'Observability service temporarily unavailable. Please retry.',
      );
    }

    // Non-axios error (should not happen)
    this.logger.error(
      'Observability proxy unexpected error: %s %s',
      method,
      path,
    );
    throw new BadGatewayException(
      'Observability service temporarily unavailable. Please retry.',
    );
  }

  /**
   * Return a safe detail message for client errors.
   *
   * CISO FIND-006: We forward upstream detail only for codes where
   * the message is application-controlled (404, 422, 400, 409).
   * For anything else, we use a generic message.
   *
   * Even for "safe" codes, we cap the detail length to prevent
   * overly verbose upstream messages from reaching the client.
   */
  private safeClientDetail(
    status: number,
    upstreamDetail: string | undefined,
  ): string {
    const SAFE_STATUS_CODES = new Set([400, 404, 409, 422]);
    const MAX_DETAIL_LENGTH = 256;

    if (
      SAFE_STATUS_CODES.has(status) &&
      upstreamDetail &&
      typeof upstreamDetail === 'string'
    ) {
      // Truncate to prevent overly verbose messages
      return upstreamDetail.length > MAX_DETAIL_LENGTH
        ? `${upstreamDetail.slice(0, MAX_DETAIL_LENGTH)}...`
        : upstreamDetail;
    }

    // Generic fallback for non-safe status codes
    const GENERIC_MESSAGES: Record<number, string> = {
      400: 'Invalid request.',
      401: 'Upstream authentication failed.',
      403: 'Access denied by upstream service.',
      404: 'Resource not found.',
      409: 'Conflict with current state.',
      422: 'Validation failed.',
      429: 'Rate limited by upstream service. Please retry later.',
    };

    return GENERIC_MESSAGES[status] ?? 'Request failed.';
  }
}
