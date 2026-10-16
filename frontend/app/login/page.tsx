import { redirect } from 'next/navigation';
import { getStaffUser, isDashboardAuthConfigured } from '../session';
import { LoginForm } from './login-form';

export const dynamic = 'force-dynamic';

export default async function LoginPage() {
  if (await getStaffUser()) redirect('/');
  return <LoginForm configured={isDashboardAuthConfigured()} />;
}
