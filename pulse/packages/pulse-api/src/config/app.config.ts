import { ConfigModule } from '@nestjs/config';
import { validateEnv } from './env.validation';
import type { EnvConfig } from './env.validation';

let cachedConfig: EnvConfig | undefined;

function loadConfig(): EnvConfig {
  if (!cachedConfig) {
    cachedConfig = validateEnv();
  }
  return cachedConfig;
}

export const AppConfigModule = ConfigModule.forRoot({
  isGlobal: true,
  load: [loadConfig],
  cache: true,
});

export function getConfig(): EnvConfig {
  return loadConfig();
}
