/**
 * Shared MSW server instance for platform tests.
 *
 * Usage in a test:
 *   import { server } from '../msw-server';
 *   server.use(http.get('/data/v1/...', () => HttpResponse.json({...})));
 *
 * The global lifecycle (start / reset / close) is handled in tests/setup.ts.
 * Individual tests add handlers via `server.use()` — these are auto-reset
 * after each test by the afterEach in setup.ts.
 */
import { setupServer } from 'msw/node';

export const server = setupServer();
