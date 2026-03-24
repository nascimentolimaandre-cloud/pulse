import { createParamDecorator, ExecutionContext } from '@nestjs/common';
import type { Request } from 'express';

interface RequestWithTenant extends Request {
  tenantId?: string;
}

/**
 * Parameter decorator that extracts the current tenant ID from the request.
 *
 * Usage:
 *   @Get()
 *   findAll(@CurrentTenant() tenantId: string) { ... }
 */
export const CurrentTenant = createParamDecorator(
  (_data: unknown, ctx: ExecutionContext): string => {
    const request = ctx.switchToHttp().getRequest<RequestWithTenant>();
    return request.tenantId ?? '00000000-0000-0000-0000-000000000001';
  },
);
