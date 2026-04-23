/**
 * Vitest global setup for tests/ (platform component, hook, and contract tests).
 *
 * This file is loaded via vitest.config.ts → test.setupFiles alongside
 * src/test/setup.ts (which handles @testing-library/jest-dom matchers).
 *
 * Responsibilities here:
 *  - Start the MSW server before all tests in this suite.
 *  - Reset handlers after each test so per-test server.use() calls don't leak.
 *  - Close the MSW server when the suite finishes.
 */
import { beforeAll, afterEach, afterAll } from 'vitest';
import { server } from './msw-server';

beforeAll(() => {
  server.listen({ onUnhandledRequest: 'warn' });
});

afterEach(() => {
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});
