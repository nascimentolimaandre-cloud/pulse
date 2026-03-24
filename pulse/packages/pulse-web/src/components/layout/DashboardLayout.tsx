import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

interface DashboardLayoutProps {
  children: React.ReactNode;
}

export function DashboardLayout({ children }: DashboardLayoutProps) {
  return (
    <div className="flex min-h-screen bg-surface-secondary">
      <Sidebar />

      {/* Main content — offset by sidebar width */}
      <div className="ml-60 flex flex-1 flex-col">
        <TopBar />

        <main className="flex-1 p-page-padding">
          <div className="mx-auto max-w-content">{children}</div>
        </main>
      </div>
    </div>
  );
}
