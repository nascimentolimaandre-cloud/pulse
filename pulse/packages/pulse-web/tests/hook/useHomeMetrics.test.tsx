/**
 * Sample 2 — Hook test: useHomeMetrics with MSW
 *
 * Tests that useHomeMetrics (TanStack Query hook) correctly:
 *  - fetches and transforms a successful response
 *  - surfaces an error when the server returns 500
 *  - reads squad_key / period from filterStore and passes them as query params
 *
 * MSW v2 in node mode intercepts at the http-interceptor level.
 * Axios in jsdom resolves relative baseURLs against window.location, which is
 * 'http://localhost/' — so the intercepted URL is 'http://localhost/data/v1/...'.
 * However, when axios cannot resolve window.location it falls back to the raw
 * path. We use a wildcard pattern '*' with path filtering to handle both cases.
 */
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { useHomeMetrics } from '@/hooks/useMetrics';
import { useFilterStore } from '@/stores/filterStore';
import { server } from '../msw-server';

// ── Fixtures ────────────────────────────────────────────────────────────────

const MOCK_HOME_RESPONSE = {
  period: '60d',
  period_start: '2026-02-22',
  period_end: '2026-04-23',
  team_id: null,
  calculated_at: '2026-04-23T10:00:00Z',
  data: {
    deployment_frequency: {
      value: 3.2,
      unit: 'deploys/day',
      level: 'high',
      trend_direction: 'up',
      trend_percentage: 10,
      previous_value: 2.9,
    },
    lead_time: {
      value: 48.5,
      unit: 'hours',
      level: 'high',
      trend_direction: 'down',
      trend_percentage: -5,
      previous_value: 51.0,
    },
    lead_time_strict: {
      value: 52.3,
      unit: 'hours',
      level: 'high',
      trend_direction: 'flat',
      trend_percentage: 0,
      previous_value: 52.3,
      coverage: { covered: 80, total: 100, pct: 0.8 },
    },
    change_failure_rate: {
      value: 0.04,
      unit: '%',
      level: 'elite',
      trend_direction: 'down',
      trend_percentage: -1,
      previous_value: 0.05,
    },
    cycle_time: {
      value: 12.5,
      unit: 'hours',
      level: 'high',
      trend_direction: 'down',
      trend_percentage: -8,
      previous_value: 13.6,
    },
    cycle_time_p85: {
      value: 28.0,
      unit: 'hours',
      level: 'medium',
      trend_direction: 'flat',
      trend_percentage: 0,
      previous_value: 28.0,
    },
    time_to_restore: {
      value: null,
      unit: 'hours',
      level: null,
      trend_direction: null,
      trend_percentage: null,
      previous_value: null,
    },
    wip: {
      value: 8,
      unit: 'items',
      level: 'high',
      trend_direction: 'down',
      trend_percentage: -2,
      previous_value: 10,
    },
    throughput: {
      value: 120,
      unit: 'PRs merged',
      level: 'elite',
      trend_direction: 'up',
      trend_percentage: 5,
      previous_value: 114,
    },
    overall_dora_level: 'high',
  },
};

// ── Test wrapper ─────────────────────────────────────────────────────────────

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        // Disable retries for tests — we want errors to surface immediately
        retry: false,
        // Prevent stale-time from hiding mismatches between runs
        staleTime: 0,
      },
    },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('useHomeMetrics', () => {
  beforeEach(() => {
    // Reset filter store to defaults before each test
    useFilterStore.getState().reset();
  });

  it('returns transformed data after a successful fetch', async () => {
    server.use(
      http.get('/data/v1/metrics/home', () =>
        HttpResponse.json(MOCK_HOME_RESPONSE),
      ),
    );

    const { result } = renderHook(() => useHomeMetrics(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const data = result.current.data!;
    expect(data.deploymentFrequency.value).toBe(3.2);
    expect(data.deploymentFrequency.classification).toBe('high');
    expect(data.throughput.value).toBe(120);
    // Strict lead time coverage should be mapped
    expect(data.leadTimeCoverage).not.toBeNull();
    expect(data.leadTimeCoverage!.pct).toBe(0.8);
    // MTTR value null is preserved (no data yet)
    expect(data.timeToRestore.value).toBeNull();
  });

  it('returns an error when the server responds with 500', async () => {
    server.use(
      http.get('/data/v1/metrics/home', () =>
        HttpResponse.json({ detail: 'Internal error' }, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useHomeMetrics(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.error).toBeTruthy();
  });

  it('forwards squad_key from filterStore as a query param', async () => {
    let capturedUrl: URL | null = null;

    server.use(
      http.get('/data/v1/metrics/home', ({ request }) => {
        capturedUrl = new URL(request.url);
        return HttpResponse.json(MOCK_HOME_RESPONSE);
      }),
    );

    // Set a squad key in the filter store
    useFilterStore.getState().setTeamId('fid');

    const { result } = renderHook(() => useHomeMetrics(), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // dataClient converts non-UUID teamId to squad_key (uppercase)
    expect(capturedUrl).not.toBeNull();
    expect(capturedUrl!.searchParams.get('squad_key')).toBe('FID');
    expect(capturedUrl!.searchParams.get('period')).toBe('60d');
  });
});
