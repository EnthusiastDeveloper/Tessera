import { useState } from 'react';
import type { FormEvent } from 'react';
import { changePassword } from '../../api/auth';
import { ApiError } from '../../api/client';

const MIN_PASSWORD_LENGTH = 12;

/** §8.1 screen 6 "Account: change password". Mirrors `SetupScreen`'s form shape
 * (current/new/confirm, client-side length + match check before the round-trip), but
 * the failure modes are different: a wrong *current* password (`invalid_credentials`)
 * is the field this form can get wrong that setup never could. Success message names
 * the session-revocation behavior explicitly (§3.6: "every session...revoked on any
 * password change") since it's the part of the action least visible to the user - their
 * own device staying logged in is exactly why no redirect-to-login happens here. */
export function AccountSection(): JSX.Element {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [currentPasswordError, setCurrentPasswordError] = useState<string | null>(null);
  const [newPasswordError, setNewPasswordError] = useState<string | null>(null);
  const [bannerError, setBannerError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    setCurrentPasswordError(null);
    setNewPasswordError(null);
    setBannerError(null);
    setSuccessMessage(null);

    if (newPassword !== confirmPassword) {
      setNewPasswordError('Passwords do not match.');
      return;
    }
    if (newPassword.length < MIN_PASSWORD_LENGTH) {
      setNewPasswordError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }

    setSubmitting(true);
    try {
      await changePassword(currentPassword, newPassword);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setSuccessMessage('Password changed. Every other signed-in device has been signed out.');
    } catch (err) {
      if (err instanceof ApiError && err.code === 'invalid_credentials') {
        setCurrentPasswordError(err.message);
      } else if (err instanceof ApiError && err.code === 'password_too_short') {
        setNewPasswordError(err.message);
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
    <section className="settings-section">
      <h3>Account</h3>
      {bannerError && (
        <div className="banner-error" role="alert">
          {bannerError}
        </div>
      )}
      {successMessage && (
        <div className="banner-success" role="status">
          {successMessage}
        </div>
      )}
      <form onSubmit={(event) => void handleSubmit(event)} noValidate>
        <div className="field">
          <label htmlFor="account-current-password">Current password</label>
          <input
            id="account-current-password"
            type="password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            autoComplete="current-password"
            required
          />
          {currentPasswordError && <p className="field-error">{currentPasswordError}</p>}
        </div>
        <div className="field">
          <label htmlFor="account-new-password">New password</label>
          <input
            id="account-new-password"
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            autoComplete="new-password"
            required
          />
        </div>
        <div className="field">
          <label htmlFor="account-confirm-password">Confirm new password</label>
          <input
            id="account-confirm-password"
            type="password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
            autoComplete="new-password"
            required
          />
          {newPasswordError && <p className="field-error">{newPasswordError}</p>}
        </div>
        <button type="submit" className="primary" disabled={submitting}>
          {submitting ? 'Changing password…' : 'Change password'}
        </button>
      </form>
    </section>
  );
}
