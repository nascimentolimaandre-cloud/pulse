import { create } from 'zustand';

export type PeriodOption = '7d' | '30d' | '60d' | '90d' | '120d' | 'custom';

export type DashboardMetric =
  | 'deployFreq'
  | 'leadTime'
  | 'cfr'
  | 'cycleTime'
  | 'wip'
  | 'throughput';

interface FilterState {
  teamId: string;
  period: PeriodOption;
  startDate: string | null;
  endDate: string | null;
  /** Active metric for the dashboard ranking + evolution sections */
  activeMetric: DashboardMetric;
}

interface FilterActions {
  setTeamId: (teamId: string) => void;
  setPeriod: (period: PeriodOption) => void;
  setCustomRange: (startDate: string, endDate: string) => void;
  setActiveMetric: (metric: DashboardMetric) => void;
  reset: () => void;
}

interface FilterStore extends FilterState, FilterActions {}

const DEFAULT_STATE: FilterState = {
  teamId: 'default',
  period: '60d',
  startDate: null,
  endDate: null,
  activeMetric: 'deployFreq',
};

export const useFilterStore = create<FilterStore>()((set) => ({
  ...DEFAULT_STATE,

  setTeamId: (teamId: string) => set({ teamId }),

  setPeriod: (period: PeriodOption) =>
    set({
      period,
      startDate: period !== 'custom' ? null : undefined,
      endDate: period !== 'custom' ? null : undefined,
    }),

  setCustomRange: (startDate: string, endDate: string) =>
    set({ period: 'custom', startDate, endDate }),

  setActiveMetric: (metric: DashboardMetric) => set({ activeMetric: metric }),

  reset: () => set(DEFAULT_STATE),
}));
