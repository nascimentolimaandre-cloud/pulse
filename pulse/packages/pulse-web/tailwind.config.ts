import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          primary: 'var(--color-brand-primary)',
          'primary-hover': 'var(--color-brand-primary-hover)',
          light: 'var(--color-brand-light)',
        },
        surface: {
          primary: 'var(--color-bg-primary)',
          secondary: 'var(--color-bg-secondary)',
          tertiary: 'var(--color-bg-tertiary)',
          elevated: 'var(--color-bg-elevated)',
        },
        content: {
          primary: 'var(--color-text-primary)',
          secondary: 'var(--color-text-secondary)',
          tertiary: 'var(--color-text-tertiary)',
          inverse: 'var(--color-text-inverse)',
        },
        border: {
          default: 'var(--color-border-default)',
          subtle: 'var(--color-border-subtle)',
        },
        status: {
          success: 'var(--color-success)',
          successBg: '#ECFDF5',
          successText: '#065F46',
          warning: 'var(--color-warning)',
          warningBg: '#FFFBEB',
          warningText: '#92400E',
          danger: 'var(--color-danger)',
          dangerBg: '#FEF2F2',
          dangerText: '#991B1B',
          info: 'var(--color-info)',
          infoBg: '#EFF6FF',
          infoText: '#1E40AF',
          idle: '#D1D5DB',
          idleBg: '#F9FAFB',
          idleText: '#6B7280',
        },
        dora: {
          elite: 'var(--color-dora-elite)',
          high: 'var(--color-dora-high)',
          medium: 'var(--color-dora-medium)',
          low: 'var(--color-dora-low)',
          'elite-bg': 'var(--color-dora-elite-bg)',
          'high-bg': 'var(--color-dora-high-bg)',
          'medium-bg': 'var(--color-dora-medium-bg)',
          'low-bg': 'var(--color-dora-low-bg)',
        },
        chart: {
          1: 'var(--chart-1)',
          2: 'var(--chart-2)',
          3: 'var(--chart-3)',
          4: 'var(--chart-4)',
          5: 'var(--chart-5)',
          6: 'var(--chart-6)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      borderRadius: {
        card: 'var(--radius-card)',
        button: 'var(--radius-button)',
        badge: 'var(--radius-badge)',
      },
      boxShadow: {
        card: 'var(--shadow-card)',
        elevated: 'var(--shadow-elevated)',
      },
      spacing: {
        'page-padding': 'var(--space-page-padding)',
        'card-padding': 'var(--space-card-padding)',
        'section-gap': 'var(--space-section-gap)',
      },
      maxWidth: {
        content: '1440px',
      },
    },
  },
  plugins: [],
};

export default config;
