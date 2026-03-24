import {
  CanActivate,
  ExecutionContext,
  Injectable,
  Logger,
} from '@nestjs/common';
import type { Request } from 'express';

const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000001';

/**
 * Ensures every request has a tenant context.
 *
 * In MVP, we always use the default tenant. In production,
 * the tenant would be resolved from the JWT or a header.
 */
@Injectable()
export class TenantGuard implements CanActivate {
  private readonly logger = new Logger(TenantGuard.name);

  canActivate(context: ExecutionContext): boolean {
    const request = context.switchToHttp().getRequest<Request>();

    // MVP: assign default tenant if none present
    const tenantId =
      (request.headers['x-tenant-id'] as string | undefined) ??
      DEFAULT_TENANT_ID;

    (request as Request & { tenantId: string }).tenantId = tenantId;

    this.logger.debug(`TenantGuard: tenant=${tenantId}`);
    return true;
  }
}
