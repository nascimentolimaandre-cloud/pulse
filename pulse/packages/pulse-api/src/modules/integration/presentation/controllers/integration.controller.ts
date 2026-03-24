import { Controller, Get } from '@nestjs/common';
import { CurrentTenant } from '@/common/decorators/current-tenant.decorator';

interface IntegrationListResponse {
  data: never[];
  meta: {
    total: number;
    tenantId: string;
  };
}

/**
 * Stub integration controller for MVP.
 * Read-only endpoint that returns an empty list.
 */
@Controller('integrations')
export class IntegrationController {
  @Get()
  findAll(@CurrentTenant() tenantId: string): IntegrationListResponse {
    return {
      data: [],
      meta: {
        total: 0,
        tenantId,
      },
    };
  }
}
