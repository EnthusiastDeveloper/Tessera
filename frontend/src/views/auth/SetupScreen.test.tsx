import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { SetupScreen } from './SetupScreen';
import * as AuthContextModule from '../../auth/AuthContext';
import { ApiError } from '../../api/client';

vi.mock('../../auth/AuthContext', async () => {
  const actual = await vi.importActual<typeof AuthContextModule>('../../auth/AuthContext');
  return { ...actual, useAuth: vi.fn() };
});

const mockedUseAuth = vi.mocked(AuthContextModule.useAuth);
const VALID_PASSWORD = 'correcthorsebatterystaple';

function completeSetupMock(): ReturnType<typeof vi.fn<[string, string], Promise<void>>> {
  return vi.fn<[string, string], Promise<void>>();
}

function renderScreen(completeSetup: (token: string, password: string) => Promise<void>): void {
  mockedUseAuth.mockReturnValue({
    status: 'setup_required',
    user: null,
    justCompletedSetup: false,
    completeSetup,
    login: vi.fn(),
    logout: vi.fn(),
  });
  render(
    <MemoryRouter>
      <SetupScreen />
    </MemoryRouter>
  );
}

async function fillForm(password: string, confirmPassword: string): Promise<void> {
  await userEvent.type(screen.getByLabelText(/setup token/i), 'the-real-token');
  await userEvent.type(screen.getByLabelText(/^password$/i), password);
  await userEvent.type(screen.getByLabelText(/confirm password/i), confirmPassword);
  await userEvent.click(screen.getByRole('button', { name: /create account/i }));
}

describe('SetupScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('submits the token and password on success', async () => {
    const completeSetup = completeSetupMock().mockResolvedValue(undefined);
    renderScreen(completeSetup);

    await fillForm(VALID_PASSWORD, VALID_PASSWORD);

    await waitFor(() =>
      expect(completeSetup).toHaveBeenCalledWith('the-real-token', VALID_PASSWORD)
    );
  });

  it('rejects mismatched passwords without calling the API', async () => {
    const completeSetup = completeSetupMock();
    renderScreen(completeSetup);

    await fillForm(VALID_PASSWORD, 'something-else-entirely');

    expect(await screen.findByText(/passwords do not match/i)).toBeInTheDocument();
    expect(completeSetup).not.toHaveBeenCalled();
  });

  it('rejects a too-short password without calling the API', async () => {
    const completeSetup = completeSetupMock();
    renderScreen(completeSetup);

    await fillForm('short', 'short');

    expect(await screen.findByText(/at least 12 characters/i)).toBeInTheDocument();
    expect(completeSetup).not.toHaveBeenCalled();
  });

  it('shows the token field error for an invalid token', async () => {
    const completeSetup = completeSetupMock().mockRejectedValue(
      new ApiError(
        401,
        'invalid_setup_token',
        'The setup token is missing, incorrect, or already used.'
      )
    );
    renderScreen(completeSetup);

    await fillForm(VALID_PASSWORD, VALID_PASSWORD);

    expect(await screen.findByText(/missing, incorrect, or already used/i)).toBeInTheDocument();
  });
});
