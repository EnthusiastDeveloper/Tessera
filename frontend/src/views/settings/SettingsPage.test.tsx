import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { SettingsPage } from './SettingsPage';
import * as settingsApi from '../../api/settings';
import * as calendarConnectionsApi from '../../api/calendarConnections';
import { ApiError } from '../../api/client';
import type { UserSettings } from '../../types/settings';

vi.mock('../../api/settings');
vi.mock('../../api/calendarConnections');

const mockedSettingsApi = vi.mocked(settingsApi);
const mockedCalendarApi = vi.mocked(calendarConnectionsApi);

const BASE_SETTINGS: UserSettings = {
  id: 'settings-1',
  timezone: 'UTC',
  active_hours: {
    monday: { start: '09:00', end: '17:00' },
    tuesday: { start: '09:00', end: '17:00' },
    wednesday: { start: '09:00', end: '17:00' },
    thursday: { start: '09:00', end: '17:00' },
    friday: { start: '09:00', end: '17:00' },
    saturday: null,
    sunday: null,
  },
  blackout_dates: [],
  daily_time_budget_minutes: {
    monday: null,
    tuesday: null,
    wednesday: null,
    thursday: null,
    friday: null,
    saturday: null,
    sunday: null,
  },
  budget_enforcement: 'soft',
  first_day_of_week: 'monday',
};

function renderAt(path: string, state?: unknown): void {
  render(
    <MemoryRouter initialEntries={[{ pathname: '/settings', state }]}>
      <Routes>
        <Route path={path} element={<SettingsPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedCalendarApi.listConnections.mockResolvedValue([]);
  });

  it('renders every §8.1 screen 6 section once settings load', async () => {
    mockedSettingsApi.getSettings.mockResolvedValue(BASE_SETTINGS);
    renderAt('/settings');

    expect(screen.getByRole('heading', { name: 'Account' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'External calendars' })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Scheduling window' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Timezone' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Display' })).toBeInTheDocument();
  });

  it('shows an error banner when settings fail to load, without blocking Account/calendars', async () => {
    mockedSettingsApi.getSettings.mockRejectedValue(new ApiError(500, 'settings_not_initialized', 'Not ready.'));
    renderAt('/settings');

    expect(await screen.findByText('Not ready.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Account' })).toBeInTheDocument();
  });

  it('passes a calendar_connected router-state hand-off through to the external calendars banner', async () => {
    mockedSettingsApi.getSettings.mockResolvedValue(BASE_SETTINGS);
    renderAt('/settings', { calendarConnected: 'google' });

    expect(await screen.findByText('Google Calendar connected.')).toBeInTheDocument();
  });
});
