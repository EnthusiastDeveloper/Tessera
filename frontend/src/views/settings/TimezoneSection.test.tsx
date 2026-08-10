import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TimezoneSection } from './TimezoneSection';
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

describe('TimezoneSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('saves the selected timezone and reports the updated settings', async () => {
    const onUpdated = vi.fn();
    const updated = { ...BASE_SETTINGS, timezone: 'America/New_York' };
    mockedSettingsApi.updateSettings.mockResolvedValue(updated);
    render(<TimezoneSection settings={BASE_SETTINGS} onUpdated={onUpdated} />);

    await userEvent.selectOptions(screen.getByLabelText(/timezone/i), 'America/New_York');
    await userEvent.click(screen.getByRole('button', { name: /save timezone/i }));

    await waitFor(() => expect(mockedSettingsApi.updateSettings).toHaveBeenCalledWith({ timezone: 'America/New_York' }));
    expect(onUpdated).toHaveBeenCalledWith(updated);
    expect(await screen.findByText('Timezone saved.')).toBeInTheDocument();
  });

  it('shows an error banner for an invalid_timezone rejection', async () => {
    mockedSettingsApi.updateSettings.mockRejectedValue(
      new ApiError(422, 'invalid_timezone', "'Not/AZone' is not a valid IANA timezone name.")
    );
    render(<TimezoneSection settings={BASE_SETTINGS} onUpdated={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: /save timezone/i }));

    expect(await screen.findByText(/is not a valid IANA timezone name/)).toBeInTheDocument();
  });
});
