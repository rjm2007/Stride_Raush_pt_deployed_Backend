import { requireStaffUser } from '../staff-session';

export const dynamic = 'force-dynamic';

// The shell (layout) draws every screen from the URL. The page only re-checks the session on each
// navigation the server sees (a shared layout is not re-rendered when only the page changes). A revisit
// within next.config.ts's staleTimes reuses this empty page; the data it shows is still checked by the
// /api/dashboard proxy on every request.
export default async function Home() {
  await requireStaffUser();
  return null;
}
