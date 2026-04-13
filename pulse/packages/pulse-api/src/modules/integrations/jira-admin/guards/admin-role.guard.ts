import {
  CanActivate,
  ExecutionContext,
  ForbiddenException,
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
 * Guard that requires the requesting user to have the `tenant_admin` role.
 *
 * In MVP, the default user stub has role='admin' which maps to tenant_admin.
 * In production, this will check JWT-derived roles.
 */
@Injectable()
export class AdminRoleGuard implements CanActivate {
  private readonly logger = new Logger(AdminRoleGuard.name);

  canActivate(context: ExecutionContext): boolean {
    const request = context.switchToHttp().getRequest<RequestWithUser>();
    const user = request.user;

    // MVP: if no user attached, check for default stub
    if (!user) {
      this.logger.debug('AdminRoleGuard: no user on request, denying access');
      throw new ForbiddenException(
        'Admin role required. No authenticated user found.',
      );
    }

    // Check roles array (production path) or single role field (MVP stub)
    const roles = user.roles ?? [user.role];
    const isAdmin =
      roles.includes('tenant_admin') || roles.includes('admin');

    if (!isAdmin) {
      this.logger.warn(
        `AdminRoleGuard: user ${user.id} denied — roles: ${roles.join(', ')}`,
      );
      throw new ForbiddenException(
        'This endpoint requires the tenant_admin role.',
      );
    }

    this.logger.debug(`AdminRoleGuard: user ${user.id} authorized`);
    return true;
  }
}
