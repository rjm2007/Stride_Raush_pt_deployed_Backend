import type { ReactNode } from 'react';
import { getDashboardRoster } from '../session';
import { DashboardShell } from '../dashboard-shell';
import { requireStaffUser } from '../staff-session';

export const dynamic = 'force-dynamic';

// The shell lives in the layout so it stays mounted between screens: before, every click remounted it,
// threw away the loaded snapshot and showed skeletons until the backend answered again.
export default async function DashboardLayout({ children }: { children: ReactNode }) {
  const user = await requireStaffUser();
  return <DashboardShell user={user} staff={getDashboardRoster()}>{children}</DashboardShell>;
}
