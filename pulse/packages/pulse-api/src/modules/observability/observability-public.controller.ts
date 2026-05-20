import {
  BadRequestException,
  Controller,
  Get,
  Query,
} from '@nestjs/common';
import { CurrentTenant } from '@/common/decorators/current-tenant.decorator';
import { ObservabilityProxyService } from './observability-proxy.service';
import { TimelineQueryDto } from './dto/timeline-query.dto';
import type { TimelineResponse } from '@pulse/shared';

/**
 * Public read-only controller for observability endpoints (FDD-OBS-001 Phase 2).
 *
 * No AdminRoleGuard — these endpoints are for the Carlos persona
 * (squad lead viewing deploy health). Tenant context is still enforced
 * via the global TenantGuard.
 *
 * Route prefix: /api/v1/obs
 * (global prefix `api/v1` is set in main.ts)
 */
@Controller('obs')
export class ObservabilityPublicController {
  constructor(private readonly proxy: ObservabilityProxyService) {}

  // ---------------------------------------------------------------------------
  // 11. GET /timeline
  // ---------------------------------------------------------------------------

  @Get('timeline')
  getTimeline(
    @CurrentTenant() tenantId: string,
    @Query() query: TimelineQueryDto,
  ): Promise<TimelineResponse> {
    // Validation: one of squad_key or service is required, not both.
    if (!query.squad_key && !query.service) {
      throw new BadRequestException(
        'One of `squad_key` or `service` is required.',
      );
    }
    if (query.squad_key && query.service) {
      throw new BadRequestException(
        'Pass `squad_key` OR `service`, not both.',
      );
    }

    return this.proxy.get<TimelineResponse>(
      'obs/timeline',
      tenantId,
      {
        squad_key: query.squad_key,
        service: query.service,
        since: query.since,
        until: query.until,
        provider: query.provider,
      },
    );
  }
}
