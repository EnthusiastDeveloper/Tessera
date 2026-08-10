import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { LoginScreen } from './LoginScreen';
import * as AuthContextModule from '../../auth/AuthContext';
import { ApiError } from '../../api/client';

vi.mock('../../auth/AuthContext', async () => {
  const actual = await vi.importActual<typeof AuthContextModule>('../../auth/AuthContext');
  return { ...actual, useAuth: vi.fn() };
});

const mockedUseAuth = vi.mocked(AuthContextModule.useAuth);

function renderScreen(
  login: (username: string, password: string) => Promise<void>,
  { justCompletedSetup = false, sessionExpired = false }: { justCompletedSetup?: boolean; sessionExpired?: boolean } = {}
): void {
  mockedUseAuth.mockReturnValue({
    status: 'unauthenticated',
    user: null,
    justCompletedSetup,
    sessionExpired,
    completeSetup: vi.fn(),
    login,
    logout: vi.fn(),
  });
  render(
    <MemoryRouter>
      <LoginScreen />
    </MemoryRouter>
  );
}

describe('LoginScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('submits the entered credentials', async () => {
    const login = vi.fn<[string, string], Promise<void>>().mockResolvedValue(undefined);
    renderScreen(login);

    await userEvent.clear(screen.getByLabelText(/username/i));
    await userEvent.type(screen.getByLabelText(/username/i), 'admin');
    await userEvent.type(screen.getByLabelText(/password/i), 'correcthorsebatterystaple');
    await userEvent.click(screen.getByRole('button', { name: /log in/i }));

    await waitFor(() => expect(login).toHaveBeenCalledWith('admin', 'correcthorsebatterystaple'));
  });

  it('shows a banner for invalid credentials', async () => {
    const login = vi
      .fn<[string, string], Promise<void>>()
      .mockRejectedValue(
        new ApiError(401, 'invalid_credentials', 'Incorrect username or password.')
      );
    renderScreen(login);

    await userEvent.type(screen.getByLabelText(/password/i), 'wrong-password');
    await userEvent.click(screen.getByRole('button', { name: /log in/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/incorrect username or password/i);
  });

  it('shows a banner for throttled login attempts', async () => {
    const login = vi
      .fn<[string, string], Promise<void>>()
      .mockRejectedValue(new ApiError(429, 'too_many_attempts', 'Too many failed login attempts.'));
    renderScreen(login);

    await userEvent.type(screen.getByLabelText(/password/i), 'wrong-password');
    await userEvent.click(screen.getByRole('button', { name: /log in/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/too many failed attempts/i);
  });

  it('greets a user who just finished first-run setup', () => {
    renderScreen(vi.fn(), { justCompletedSetup: true });
    expect(screen.getByRole('status')).toHaveTextContent(/account created/i);
  });

  it('does not show the setup greeting on an ordinary visit', () => {
    renderScreen(vi.fn());
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('explains a redirect caused by a mid-app session expiry', () => {
    renderScreen(vi.fn(), { sessionExpired: true });
    expect(screen.getByRole('status')).toHaveTextContent(/session expired/i);
  });

  it('prefers the setup greeting over the session-expired message if somehow both are true', () => {
    renderScreen(vi.fn(), { justCompletedSetup: true, sessionExpired: true });
    expect(screen.getByRole('status')).toHaveTextContent(/account created/i);
  });
});
