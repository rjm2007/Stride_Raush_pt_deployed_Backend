import { cache } from 'react';
import { redirect } from 'next/navigation';
import { getStaffUser } from './session';

// Server-only. The dashboard layout and its page both need the signed-in staff member; React.cache
// shares one cookie check between them within a single request. Every request still runs the full
// check (signature, expiry, credential version): nothing is remembered across requests.
export const getRequestStaffUser = cache(getStaffUser);

export async function requireStaffUser() {
  const user = await getRequestStaffUser();
  if (!user) redirect('/login');
  return user;
}
