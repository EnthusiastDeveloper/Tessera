import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthProvider, useAuth } from './AuthContext';
import { apiClient } from '../api/client';

function mockFetchResponse(status: number, body: unknown): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      status,
      ok: status >= 200 && status < 300,
      text: () => Promise.resolve(JSON.stringify(body)),
    })
  );
}

function Probe(): JSX.Element {
  const { status, sessionExpired, login } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="session-expired">{String(sessionExpired)}</span>
      <button onClick={() => void login('admin', 'correcthorsebatterystaple')}>log in</button>
    </div>
  );
}

describe('AuthProvider', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('flips to unauthenticated and flags sessionExpired when any later call gets session_expired', async () => {
    // Mount as already authenticated (the initial `GET /auth/me` succeeds)...
    mockFetchResponse(200, { id: 'user-1', username: 'admin' });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(screen.getByTestId('session-expired')).toHaveTextContent('false');

    // ...then some unrelated later call (any screen, any endpoint) comes back
    // session_expired, e.g. because the 30-day TTL elapsed mid-session.
    mockFetchResponse(401, { code: 'session_expired', message: 'Authentication required.' });
    await act(() => expect(apiClient.get('/task-instances')).rejects.toThrow());

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'));
    expect(screen.getByTestId('session-expired')).toHaveTextContent('true');
  });

  it('does not react to an unrelated error code from a later call', async () => {
    mockFetchResponse(200, { id: 'user-1', username: 'admin' });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));

    mockFetchResponse(422, { code: 'invalid_field', message: 'Bad field.' });
    await act(() => expect(apiClient.get('/task-instances')).rejects.toThrow());

    expect(screen.getByTestId('status')).toHaveTextContent('authenticated');
    expect(screen.getByTestId('session-expired')).toHaveTextContent('false');
  });

  it('clears sessionExpired on a fresh login', async () => {
    mockFetchResponse(401, { code: 'session_expired', message: 'Authentication required.' });
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );
    await waitFor(() => expect(screen.getByTestId('session-expired')).toHaveTextContent('true'));

    mockFetchResponse(200, { id: 'user-1', username: 'admin' });
    await userEvent.click(screen.getByRole('button', { name: /log in/i }));

    await waitFor(() => expect(screen.getByTestId('session-expired')).toHaveTextContent('false'));
  });
});
