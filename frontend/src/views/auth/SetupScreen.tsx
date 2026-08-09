import { useState } from 'react';
import type { FormEvent } from 'react';
import { useAuth } from '../../auth/AuthContext';
import { ApiError } from '../../api/client';

const MIN_PASSWORD_LENGTH = 12;

export function SetupScreen(): JSX.Element {
  const { completeSetup } = useAuth();

  const [token, setToken] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [tokenError, setTokenError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [bannerError, setBannerError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setTokenError(null);
    setPasswordError(null);
    setBannerError(null);

    if (password !== confirmPassword) {
      setPasswordError('Passwords do not match.');
      return;
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setPasswordError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }

    setSubmitting(true);
    try {
      // No navigate() here on purpose - RouteGuard redirects to /login once `status`
      // flips inside completeSetup (see AuthContext.tsx); navigating imperatively too
      // would race that redirect.
      await completeSetup(token, password);
    } catch (err) {
      if (err instanceof ApiError && err.code === 'invalid_setup_token') {
        setTokenError(err.message);
      } else if (err instanceof ApiError && err.code === 'password_too_short') {
        setPasswordError(err.message);
      } else if (err instanceof ApiError) {
        setBannerError(err.message);
      } else {
        setBannerError('Could not reach the server.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="centered-screen">
      <div className="auth-card">
        <h1>Set up Tessera</h1>
        <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)' }}>
          Find the setup token in the server startup log (search for &quot;Setup token&quot;), then
          choose an admin password.
        </p>
        {bannerError && (
          <div className="banner-error" role="alert">
            {bannerError}
          </div>
        )}
        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor="setup-token">Setup token</label>
            <input
              id="setup-token"
              type="text"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              required
            />
            {tokenError && <p className="field-error">{tokenError}</p>}
          </div>
          <div className="field">
            <label htmlFor="setup-password">Password</label>
            <input
              id="setup-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="setup-confirm-password">Confirm password</label>
            <input
              id="setup-confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              autoComplete="new-password"
              required
            />
            {passwordError && <p className="field-error">{passwordError}</p>}
          </div>
          <button type="submit" className="primary" disabled={submitting}>
            {submitting ? 'Creating account…' : 'Create account'}
          </button>
        </form>
      </div>
    </div>
  );
}
