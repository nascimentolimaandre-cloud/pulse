import { describe, it, expect } from 'vitest';
import { formatDuration } from '../formatDuration';

describe('formatDuration', () => {
  describe('null / NaN / Infinity bucket', () => {
    it('returns em-dash for null', () => {
      expect(formatDuration(null)).toEqual({ primary: '—', secondary: null });
    });
    it('returns em-dash for NaN', () => {
      expect(formatDuration(Number.NaN)).toEqual({ primary: '—', secondary: null });
    });
    it('returns em-dash for +Infinity', () => {
      expect(formatDuration(Number.POSITIVE_INFINITY)).toEqual({ primary: '—', secondary: null });
    });
    it('returns em-dash for -Infinity', () => {
      expect(formatDuration(Number.NEGATIVE_INFINITY)).toEqual({ primary: '—', secondary: null });
    });
  });

  describe('< 1 min bucket', () => {
    it('renders "<1 min" for tiny values (0.005h ≈ 18s)', () => {
      expect(formatDuration(0.005)).toEqual({ primary: '<1 min', secondary: null });
    });
    it('renders "<1 min" for exact zero', () => {
      expect(formatDuration(0)).toEqual({ primary: '<1 min', secondary: null });
    });
  });

  describe('< 1h bucket (minutes primary, hours secondary)', () => {
    it('renders 45min for 0.75h', () => {
      expect(formatDuration(0.75)).toEqual({ primary: '45min', secondary: '(0,75h)' });
    });
    it('renders 30min for 0.5h (secondary always 2 decimals in <1h bucket)', () => {
      expect(formatDuration(0.5)).toEqual({ primary: '30min', secondary: '(0,50h)' });
    });
    it('renders 1min for ~0.017h (1 min exactly)', () => {
      expect(formatDuration(1 / 60)).toEqual({ primary: '1min', secondary: '(0,02h)' });
    });
  });

  describe('1h ≤ v < 24h bucket (hours, no secondary)', () => {
    it('renders 16,9h for 16.9', () => {
      expect(formatDuration(16.9)).toEqual({ primary: '16,9h', secondary: null });
    });
    it('renders 1,2h for 1.2', () => {
      expect(formatDuration(1.2)).toEqual({ primary: '1,2h', secondary: null });
    });
    it('renders integer 5h without decimals', () => {
      expect(formatDuration(5)).toEqual({ primary: '5h', secondary: null });
    });
    it('renders 23,9h (boundary just below 24)', () => {
      expect(formatDuration(23.9)).toEqual({ primary: '23,9h', secondary: null });
    });
  });

  describe('≥ 24h bucket (days primary, hours secondary)', () => {
    it('renders 16,9 dias with (404,7h) secondary — OKM 60d Lead Time case', () => {
      expect(formatDuration(404.7)).toEqual({ primary: '16,9 dias', secondary: '(404,7h)' });
    });
    it('renders 4,0 dias with (96,3h) secondary — OKM P85 case', () => {
      expect(formatDuration(96.3)).toEqual({ primary: '4,0 dias', secondary: '(96,3h)' });
    });
    it('renders exact 24h as 1 dias', () => {
      expect(formatDuration(24)).toEqual({ primary: '1 dias', secondary: '(24h)' });
    });
    it('renders integer 48h as 2 dias', () => {
      expect(formatDuration(48)).toEqual({ primary: '2 dias', secondary: '(48h)' });
    });
    it('renders 5,0 d inclusive fallback (Lead Time inclusive=120h)', () => {
      expect(formatDuration(120)).toEqual({ primary: '5 dias', secondary: '(120h)' });
    });
  });
});
