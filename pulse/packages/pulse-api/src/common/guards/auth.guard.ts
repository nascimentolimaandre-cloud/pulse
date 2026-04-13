import {
  CanActivate,
  ExecutionContext,
  Injectable,
  Logger,
} from '@nestjs/common';
import type { Request } from 'express';

interface RequestWithUser extends Request {
  user?: {
    id: string;
    role: string;
    roles?: string[];
  };
}

/**
 * Auth guard stub for MVP.
 *
 * MVP has no authentication: this guard always returns true and attaches
 * a stub admin user so downstream guards (AdminRoleGuard) can authorize
 * the dev tenant.
 *
 * In production this will validate JWT tokens and attach the real user.
 */
@Injectable()
export class AuthGuard implements CanActivate {
  private readonly logger = new Logger(AuthGuard.name);

  canActivate(context: ExecutionContext): boolean {
    const request = context.switchToHttp().getRequest<RequestWithUser>();

    if (!request.user) {
      // MVP dev stub: tenant_admin so admin endpoints work without JWT
      request.user = {
        id: '00000000-0000-0000-0000-0000000000aa',
        role: 'tenant_admin',
        roles: ['tenant_admin'],
      };
    }

    this.logger.debug('AuthGuard: MVP passthrough — stub user attached');
    return true;
  }
}
