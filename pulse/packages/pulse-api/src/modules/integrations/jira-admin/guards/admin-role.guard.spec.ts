import { ExecutionContext, ForbiddenException } from '@nestjs/common';
import { AdminRoleGuard } from './admin-role.guard';

function createMockContext(user?: Record<string, unknown>): ExecutionContext {
  return {
    switchToHttp: () => ({
      getRequest: () => ({ user }),
    }),
  } as unknown as ExecutionContext;
}

describe('AdminRoleGuard', () => {
  let guard: AdminRoleGuard;

  beforeEach(() => {
    guard = new AdminRoleGuard();
  });

  it('should allow user with tenant_admin role', () => {
    const ctx = createMockContext({
      id: 'u1',
      roles: ['tenant_admin'],
      role: 'tenant_admin',
    });
    expect(guard.canActivate(ctx)).toBe(true);
  });

  it('should allow user with admin role (MVP stub)', () => {
    const ctx = createMockContext({
      id: 'u1',
      role: 'admin',
    });
    expect(guard.canActivate(ctx)).toBe(true);
  });

  it('should deny user with member role', () => {
    const ctx = createMockContext({
      id: 'u1',
      role: 'member',
    });
    expect(() => guard.canActivate(ctx)).toThrow(ForbiddenException);
  });

  it('should deny when no user on request', () => {
    const ctx = createMockContext(undefined);
    expect(() => guard.canActivate(ctx)).toThrow(ForbiddenException);
  });

  it('should check roles array over single role field', () => {
    const ctx = createMockContext({
      id: 'u1',
      roles: ['viewer', 'tenant_admin'],
      role: 'viewer',
    });
    expect(guard.canActivate(ctx)).toBe(true);
  });
});
