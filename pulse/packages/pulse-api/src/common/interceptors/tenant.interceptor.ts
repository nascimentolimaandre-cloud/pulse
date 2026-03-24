import {
  CallHandler,
  ExecutionContext,
  Injectable,
  Logger,
  NestInterceptor,
} from '@nestjs/common';
import { DataSource } from 'typeorm';
import type { Request } from 'express';
import { Observable, from, switchMap } from 'rxjs';

const DEFAULT_TENANT_ID = '00000000-0000-0000-0000-000000000001';

interface RequestWithTenant extends Request {
  tenantId?: string;
}

/**
 * Sets `app.current_tenant` on the PostgreSQL connection
 * for every request, enabling Row-Level Security (RLS).
 */
@Injectable()
export class TenantInterceptor implements NestInterceptor {
  private readonly logger = new Logger(TenantInterceptor.name);

  constructor(private readonly dataSource: DataSource) {}

  intercept(
    context: ExecutionContext,
    next: CallHandler,
  ): Observable<unknown> {
    const request = context.switchToHttp().getRequest<RequestWithTenant>();
    const tenantId = request.tenantId ?? DEFAULT_TENANT_ID;

    return from(this.setTenantContext(tenantId)).pipe(
      switchMap(() => next.handle()),
    );
  }

  private async setTenantContext(tenantId: string): Promise<void> {
    // Validate UUID format to prevent SQL injection (SET doesn't support $1 params)
    const uuidRegex =
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (!uuidRegex.test(tenantId)) {
      throw new Error(`Invalid tenant ID format: ${tenantId}`);
    }

    const queryRunner = this.dataSource.createQueryRunner();
    try {
      await queryRunner.query(`SET app.current_tenant = '${tenantId}'`);
      this.logger.debug(`RLS tenant context set: ${tenantId}`);
    } finally {
      await queryRunner.release();
    }
  }
}
