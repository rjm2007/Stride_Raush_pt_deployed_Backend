'use client';

import { useRouter } from 'next/navigation';
import { FormEvent, useState } from 'react';

export function LoginForm({ configured }: { configured: boolean }) {
  const router = useRouter();
  const [employeeId, setEmployeeId] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ employee_id: employeeId, password }),
      });
      if (!response.ok) {
        throw new Error(response.status === 401 ? 'The login ID or password is incorrect.' : 'Sign-in is temporarily unavailable. Please try again.');
      }
      router.replace('/');
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Sign-in failed.');
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={submit}>
        <h1>Outreach Operations CRM</h1>
        <p className="login-hint">Staff sign-in required.</p>

        {!configured && (
          <p className="login-error" role="alert">
            Sign-in is unavailable. Please contact your administrator.
          </p>
        )}

        <label className="field-label">
          Employee ID or email
          <input
            value={employeeId}
            onChange={(event) => setEmployeeId(event.target.value.toLowerCase())}
            autoComplete="username"
            maxLength={254}
            required
          />
        </label>

        <label className="field-label">
          Staff password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {error && (
          <p className="login-error" role="alert">
            {error}
          </p>
        )}

        <button className="primary full" type="submit" disabled={busy || !configured}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  );
}
