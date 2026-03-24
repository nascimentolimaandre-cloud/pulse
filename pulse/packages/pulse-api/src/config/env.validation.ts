import { z } from 'zod';
import { Logger } from '@nestjs/common';

export const envSchema = z.object({
  NODE_ENV: z
    .enum(['development', 'production', 'test'])
    .default('development'),

  PORT: z.coerce.number().default(3000),

  DATABASE_URL: z
    .string()
    .url()
    .describe('PostgreSQL connection string'),

  KAFKA_BROKERS: z
    .string()
    .describe('Comma-separated list of Kafka broker addresses'),

  DEVLAKE_API_URL: z
    .string()
    .url()
    .describe('DevLake REST API base URL'),

  REDIS_URL: z
    .string()
    .url()
    .describe('Redis connection URL'),

  JWT_SECRET: z
    .string()
    .optional()
    .describe('JWT signing secret — optional for MVP'),

  CORS_ORIGIN: z
    .string()
    .default('http://localhost:5173'),

  DEFAULT_TENANT_ID: z
    .string()
    .uuid()
    .default('00000000-0000-0000-0000-000000000001')
    .describe('Default tenant UUID for MVP (no auth)'),
});

export type EnvConfig = z.infer<typeof envSchema>;

export function validateEnv(): EnvConfig {
  const logger = new Logger('EnvValidation');

  const result = envSchema.safeParse(process.env);

  if (!result.success) {
    const formatted = result.error.issues
      .map((issue) => `  - ${issue.path.join('.')}: ${issue.message}`)
      .join('\n');

    logger.error(`Environment validation failed:\n${formatted}`);
    throw new Error(`Environment validation failed:\n${formatted}`);
  }

  logger.log('Environment variables validated successfully');
  return result.data;
}
