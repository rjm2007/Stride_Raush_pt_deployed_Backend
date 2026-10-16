import { redirect } from 'next/navigation';
import { getDashboardRoster, getStaffUser } from './session';
import { DashboardShell } from './dashboard-shell';

export const dynamic = 'force-dynamic';

export default async function Home() {
  const user = await getStaffUser();
  if (!user) redirect('/login');

  return <DashboardShell user={user} staff={getDashboardRoster()} />;
}
