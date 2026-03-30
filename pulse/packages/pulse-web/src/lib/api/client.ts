import axios from 'axios';
import type { AxiosError, InternalAxiosRequestConfig } from 'axios';

/**
 * Axios client for pulse-api (NestJS CRUD API).
 * Proxied via Vite dev server: /api -> localhost:3000
 */
export const apiClient = axios.create({
  baseURL: '/api',
  timeout: 15_000,
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Axios client for pulse-data (FastAPI data/metrics API).
 * Proxied via Vite dev server: /data -> localhost:8000
 */
export const dataClient = axios.create({
  baseURL: '/data/v1',
  timeout: 30_000,
  headers: {
    'Content-Type': 'application/json',
  },
});

/** MVP: Auth interceptor stub — no token attached */
function attachAuthHeader(config: InternalAxiosRequestConfig): InternalAxiosRequestConfig {
  // MVP: No auth token. Default tenant resolved server-side.
  return config;
}

/** Shared error handler */
function handleResponseError(error: AxiosError): Promise<never> {
  if (error.response) {
    const status = error.response.status;

    if (status === 401 || status === 403) {
      // MVP: No auth redirect. Log and reject.
      console.error(`[API] Auth error ${status}:`, error.response.data);
    }

    if (status >= 500) {
      console.error(`[API] Server error ${status}:`, error.response.data);
    }
  } else if (error.request) {
    console.error('[API] Network error — no response received');
  }

  return Promise.reject(error);
}

// Attach interceptors
apiClient.interceptors.request.use(attachAuthHeader);
apiClient.interceptors.response.use((r) => r, handleResponseError);

dataClient.interceptors.request.use(attachAuthHeader);
dataClient.interceptors.response.use((r) => r, handleResponseError);
