import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AccountSection } from './AccountSection';
import * as authApi from '../../api/auth';
import { ApiError } from '../../api/client';

vi.mock('../../api/auth');

const mockedAuthApi = vi.mocked(authApi);
const VALID_NEW_PASSWORD = 'a-brand-new-password-123';

async function fillForm(current: string, next: string, confirm: string): Promise<void> {
  await userEvent.type(screen.getByLabelText(/current password/i), current);
  await userEvent.type(screen.getByLabelText(/^new password$/i), next);
  await userEvent.type(screen.getByLabelText(/confirm new password/i), confirm);
  await userEvent.click(screen.getByRole('button', { name: /change password/i }));
}

describe('AccountSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('submits current/new password and shows a success message that names session revocation', async () => {
    mockedAuthApi.changePassword.mockResolvedValue({ id: 'u1', username: 'admin' });
    render(<AccountSection />);

    await fillForm('old-password-123', VALID_NEW_PASSWORD, VALID_NEW_PASSWORD);

    await waitFor(() => expect(mockedAuthApi.changePassword).toHaveBeenCalledWith('old-password-123', VALID_NEW_PASSWORD));
    expect(await screen.findByText(/every other signed-in device has been signed out/i)).toBeInTheDocument();
  });

  it('rejects mismatched confirmation without calling the API', async () => {
    render(<AccountSection />);
    await fillForm('old-password-123', VALID_NEW_PASSWORD, 'something-else-entirely');

    expect(screen.getByText(/passwords do not match/i)).toBeInTheDocument();
    expect(mockedAuthApi.changePassword).not.toHaveBeenCalled();
  });

  it('rejects a too-short new password without calling the API', async () => {
    render(<AccountSection />);
    await fillForm('old-password-123', 'short', 'short');

    expect(screen.getByText(/at least 12 characters/i)).toBeInTheDocument();
    expect(mockedAuthApi.changePassword).not.toHaveBeenCalled();
  });

  it('shows a field-level error under "current password" for a wrong current password', async () => {
    mockedAuthApi.changePassword.mockRejectedValue(new ApiError(401, 'invalid_credentials', 'Current password is incorrect.'));
    render(<AccountSection />);

    await fillForm('wrong-current', VALID_NEW_PASSWORD, VALID_NEW_PASSWORD);

    expect(await screen.findByText('Current password is incorrect.')).toBeInTheDocument();
  });
});
