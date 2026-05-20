import { Module } from '@nestjs/common';
import { ObservabilityAdminController } from './observability-admin.controller';
import { ObservabilityPublicController } from './observability-public.controller';
import { ObservabilityProxyService } from './observability-proxy.service';

/**
 * Thin HTTP proxy module for observability endpoints (FDD-OBS-001 Phase 2).
 *
 * All business logic lives in pulse-data (FastAPI). This module simply
 * forwards requests to pulse-data and returns sanitized responses, so
 * pulse-web talks to a single backend (NestJS :3000).
 *
 * Admin endpoints: /api/v1/admin/integrations/...
 * Public endpoints: /api/v1/obs/...
 */
@Module({
  controllers: [ObservabilityAdminController, ObservabilityPublicController],
  providers: [ObservabilityProxyService],
})
export class ObservabilityModule {}
