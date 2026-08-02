import { redirect } from 'next/navigation';
import { createClient } from '@/lib/supabase/server';
import { AppSidebar } from '@/components/layout/Sidebar';
import { AppHeader } from '@/components/layout/Header';

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) {
    redirect('/login');
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Sidebar */}
      <AppSidebar user={user} />

      {/* Main content area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <AppHeader user={user} />
        {/* The content region. Inset on an 8pt rhythm and capped in width —
            a dashboard that stretches body text across a 2000px monitor is
            unreadable, and macOS apps always inset their content. */}
        <main className="flex-1 overflow-auto">
          <div className="mx-auto w-full max-w-6xl px-6 py-8 sm:px-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
