import { useState } from 'react';
import type { FormEvent } from 'react';
import { useAuth } from '../../auth/AuthContext';
import { ApiError } from '../../api/client';

const ERROR_MESSAGES: Record<string, string> = {
  invalid_credentials: 'Incorrect username or password.',
  too_many_attempts: 'Too many failed attempts. Try again later.',
};

export function LoginScreen(): JSX.Element {
  const { login, justCompletedSetup, sessionExpired } = useAuth();

  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? (ERROR_MESSAGES[err.code] ?? err.message)
          : 'Could not reach the server.';
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="centered-screen">
      <div className="auth-card">
        <h1>Tessera</h1>
        {justCompletedSetup && (
          <p role="status" style={{ color: 'var(--color-success)' }}>
            Account created. Log in below.
          </p>
        )}
        {sessionExpired && !justCompletedSetup && (
          <p role="status" style={{ color: 'var(--color-warning)' }}>
            Your session expired. Log in again.
          </p>
        )}
        {error && (
          <div className="banner-error" role="alert">
            {error}
          </div>
        )}
        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor="username">Username</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          <button type="submit" className="primary" disabled={submitting}>
            {submitting ? 'Logging in…' : 'Log in'}
          </button>
        </form>
      </div>
    </div>
  );
}
