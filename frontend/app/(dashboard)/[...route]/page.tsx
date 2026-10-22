import { requireStaffUser } from '../../staff-session';

export const dynamic = 'force-dynamic';

// See ../page.tsx: the shell renders the screen; this page keeps the per-navigation session check.
export default async function DashboardRoute() {
  await requireStaffUser();
  return null;
}
