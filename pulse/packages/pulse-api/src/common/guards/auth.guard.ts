import {
  CanActivate,
  ExecutionContext,
  Injectable,
  Logger,
} from '@nestjs/common';

/**
 * Auth guard stub for MVP.
 *
 * MVP has no authentication. This guard always returns true.
 * In production, this will validate JWT tokens and attach
 * the authenticated user to the request.
 */
@Injectable()
export class AuthGuard implements CanActivate {
  private readonly logger = new Logger(AuthGuard.name);

  canActivate(_context: ExecutionContext): boolean {
    this.logger.debug('AuthGuard: MVP passthrough — no auth enforced');
    return true;
  }
}
