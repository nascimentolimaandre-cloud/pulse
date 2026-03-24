import { createRootRoute, Outlet } from '@tanstack/react-router';
import { DashboardLayout } from '@/components/layout/DashboardLayout';

export const rootRoute = createRootRoute({
  component: RootLayout,
});

function RootLayout() {
  return (
    <DashboardLayout>
      <Outlet />
    </DashboardLayout>
  );
}
