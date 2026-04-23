import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@pulse/shared': path.resolve(__dirname, '../pulse-shared/src/index.ts'),
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts', './tests/setup.ts'],
    css: true,
    include: [
      'src/**/*.{test,spec}.{ts,tsx}',
      'tests/**/*.{test,spec}.{ts,tsx}',
    ],
    exclude: [
      'node_modules',
      'dist',
      'tests/e2e/**',
    ],
  },
});
