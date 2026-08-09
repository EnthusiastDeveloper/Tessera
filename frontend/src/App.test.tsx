import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import App from './App';
import * as authApi from './api/auth';
import { ApiError } from './api/client';

vi.mock('./api/auth');

const mockedAuthApi = vi.mocked(authApi);

describe('App', () => {
  it('redirects to the login screen when no session exists', async () => {
    mockedAuthApi.me.mockRejectedValue(
      new ApiError(401, 'unauthenticated', 'Authentication required.')
    );
    render(<App />);
    expect(await screen.findByRole('heading', { name: /tessera/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
  });

  it('redirects to the setup screen while no account exists yet', async () => {
    mockedAuthApi.me.mockRejectedValue(
      new ApiError(403, 'setup_required', 'No account exists yet.')
    );
    render(<App />);
    expect(await screen.findByRole('heading', { name: /set up tessera/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/setup token/i)).toBeInTheDocument();
  });

  it('renders the app shell when a session is already valid', async () => {
    mockedAuthApi.me.mockResolvedValue({ id: 'u1', username: 'admin' });
    render(<App />);
    await waitFor(() => expect(screen.getByText('admin')).toBeInTheDocument());
    expect(screen.getByRole('heading', { name: /timeline/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /settings/i })).toBeInTheDocument();
  });
});
