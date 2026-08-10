import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DisplaySection } from './DisplaySection';
import * as settingsApi from '../../api/settings';
import { ApiError } from '../../api/client';
import type { UserSettings } from '../../types/settings';

vi.mock('../../api/settings');

const mockedSettingsApi = vi.mocked(settingsApi);

const BASE_SETTINGS: UserSettings = {
  id: 'settings-1',
  timezone: 'UTC',
  active_hours: {},
  blackout_dates: [],
  daily_time_budget_minutes: {},
  budget_enforcement: 'soft',
  first_day_of_week: 'monday',
};

describe('DisplaySection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('saves the selected first day of the week and reports the updated settings', async () => {
    const onUpdated = vi.fn();
    const updated = { ...BASE_SETTINGS, first_day_of_week: 'sunday' as const };
    mockedSettingsApi.updateSettings.mockResolvedValue(updated);
    render(<DisplaySection settings={BASE_SETTINGS} onUpdated={onUpdated} />);

    await userEvent.selectOptions(screen.getByLabelText(/first day of the week/i), 'sunday');
    await userEvent.click(screen.getByRole('button', { name: /save display preference/i }));

    await waitFor(() => expect(mockedSettingsApi.updateSettings).toHaveBeenCalledWith({ first_day_of_week: 'sunday' }));
    expect(onUpdated).toHaveBeenCalledWith(updated);
    expect(await screen.findByText('Display preference saved.')).toBeInTheDocument();
  });

  it('shows an error banner when the save fails', async () => {
    mockedSettingsApi.updateSettings.mockRejectedValue(new ApiError(500, 'settings_not_initialized', 'Not ready.'));
    render(<DisplaySection settings={BASE_SETTINGS} onUpdated={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: /save display preference/i }));

    expect(await screen.findByText('Not ready.')).toBeInTheDocument();
  });
});
