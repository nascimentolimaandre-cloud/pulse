import { create } from 'zustand';

export type PeriodOption = '7d' | '30d' | '90d' | 'custom';

interface FilterState {
  teamId: string;
  period: PeriodOption;
  startDate: string | null;
  endDate: string | null;
}

interface FilterActions {
  setTeamId: (teamId: string) => void;
  setPeriod: (period: PeriodOption) => void;
  setCustomRange: (startDate: string, endDate: string) => void;
  reset: () => void;
}

interface FilterStore extends FilterState, FilterActions {}

const DEFAULT_STATE: FilterState = {
  teamId: 'default',
  period: '30d',
  startDate: null,
  endDate: null,
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

  reset: () => set(DEFAULT_STATE),
}));
