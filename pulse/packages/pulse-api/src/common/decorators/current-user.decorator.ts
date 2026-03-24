import { createParamDecorator, ExecutionContext } from '@nestjs/common';
import type { Request } from 'express';

export interface CurrentUserPayload {
  id: string;
  email: string;
  name: string;
  orgId: string;
  role: string;
}

interface RequestWithUser extends Request {
  user?: CurrentUserPayload;
}

/**
 * Parameter decorator that extracts the current user from the request.
 *
 * MVP stub: returns a default user. In production, this will be
 * populated by the AuthGuard from the validated JWT.
 *
 * Usage:
 *   @Get('me')
 *   getProfile(@CurrentUser() user: CurrentUserPayload) { ... }
 */
export const CurrentUser = createParamDecorator(
  (_data: unknown, ctx: ExecutionContext): CurrentUserPayload => {
    const request = ctx.switchToHttp().getRequest<RequestWithUser>();
    return (
      request.user ?? {
        id: '00000000-0000-0000-0000-000000000001',
        email: 'admin@pulse.dev',
        name: 'MVP Admin',
        orgId: '00000000-0000-0000-0000-000000000001',
        role: 'admin',
      }
    );
  },
);
