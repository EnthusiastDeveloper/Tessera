import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SchedulingWindowSection } from './SchedulingWindowSection';
import * as settingsApi from '../../api/settings';
import { ApiError } from '../../api/client';
import type { UserSettings } from '../../types/settings';

vi.mock('../../api/settings');

const mockedSettingsApi = vi.mocked(settingsApi);

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
  blackout_dates: [{ start: '2026-12-25', end: '2026-12-25', label: 'Holiday' }],
  daily_time_budget_minutes: {
    monday: 120,
    tuesday: 120,
    wednesday: 120,
    thursday: 120,
    friday: 120,
    saturday: null,
    sunday: null,
  },
  budget_enforcement: 'soft',
  first_day_of_week: 'monday',
};

describe('SchedulingWindowSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders existing blackout dates and active-hours state', () => {
    render(<SchedulingWindowSection settings={BASE_SETTINGS} onUpdated={vi.fn()} />);
    expect(screen.getByText(/2026-12-25.*Holiday/)).toBeInTheDocument();
    expect(screen.getByLabelText('Saturday active hours')).toHaveValue('excluded');
    expect(screen.getByLabelText('Monday active hours')).toHaveValue('custom');
  });

  it('saves the full active-hours/budget maps and reports the updated settings', async () => {
    const onUpdated = vi.fn();
    const updated = { ...BASE_SETTINGS, budget_enforcement: 'strict' as const };
    mockedSettingsApi.updateSettings.mockResolvedValue(updated);
    render(<SchedulingWindowSection settings={BASE_SETTINGS} onUpdated={onUpdated} />);

    await userEvent.selectOptions(screen.getByLabelText(/budget enforcement/i), 'strict');
    await userEvent.click(screen.getByRole('button', { name: /save scheduling window/i }));

    await waitFor(() => expect(mockedSettingsApi.updateSettings).toHaveBeenCalled());
    const patch = mockedSettingsApi.updateSettings.mock.calls[0][0];
    expect(patch.budget_enforcement).toBe('strict');
    expect(Object.keys(patch.active_hours ?? {})).toHaveLength(7);
    expect(Object.keys(patch.daily_time_budget_minutes ?? {})).toHaveLength(7);
    expect(onUpdated).toHaveBeenCalledWith(updated);
    expect(await screen.findByText('Scheduling window saved.')).toBeInTheDocument();
  });

  it('excluding a day removes its window from the saved patch', async () => {
    mockedSettingsApi.updateSettings.mockResolvedValue(BASE_SETTINGS);
    render(<SchedulingWindowSection settings={BASE_SETTINGS} onUpdated={vi.fn()} />);

    await userEvent.selectOptions(screen.getByLabelText('Monday active hours'), 'excluded');
    await userEvent.click(screen.getByRole('button', { name: /save scheduling window/i }));

    await waitFor(() => expect(mockedSettingsApi.updateSettings).toHaveBeenCalled());
    const patch = mockedSettingsApi.updateSettings.mock.calls[0][0];
    expect(patch.active_hours?.monday).toBeNull();
  });

  it('adds a blackout date', async () => {
    render(<SchedulingWindowSection settings={BASE_SETTINGS} onUpdated={vi.fn()} />);

    await userEvent.type(screen.getByLabelText('Start'), '2026-07-01');
    await userEvent.type(screen.getByLabelText('End'), '2026-07-04');
    await userEvent.type(screen.getByLabelText(/label/i), 'Trip');
    await userEvent.click(screen.getByRole('button', { name: /add blackout date/i }));

    expect(screen.getByText(/2026-07-01.*2026-07-04.*Trip/)).toBeInTheDocument();
  });

  it('rejects a blackout date whose end precedes its start, without adding it', async () => {
    render(<SchedulingWindowSection settings={BASE_SETTINGS} onUpdated={vi.fn()} />);

    await userEvent.type(screen.getByLabelText('Start'), '2026-07-10');
    await userEvent.type(screen.getByLabelText('End'), '2026-07-01');
    await userEvent.click(screen.getByRole('button', { name: /add blackout date/i }));

    expect(screen.getByText(/end date must be on or after/i)).toBeInTheDocument();
    expect(screen.queryByText(/2026-07-10/)).not.toBeInTheDocument();
  });

  it('removes a blackout date', async () => {
    render(<SchedulingWindowSection settings={BASE_SETTINGS} onUpdated={vi.fn()} />);
    await userEvent.click(screen.getByRole('button', { name: /remove blackout date 1/i }));
    expect(screen.queryByText(/Holiday/)).not.toBeInTheDocument();
  });

  it('toggling "Unlimited" for a day clears its budget in the saved patch', async () => {
    mockedSettingsApi.updateSettings.mockResolvedValue(BASE_SETTINGS);
    render(<SchedulingWindowSection settings={BASE_SETTINGS} onUpdated={vi.fn()} />);

    await userEvent.click(screen.getByLabelText('Monday unlimited budget'));
    await userEvent.click(screen.getByRole('button', { name: /save scheduling window/i }));

    await waitFor(() => expect(mockedSettingsApi.updateSettings).toHaveBeenCalled());
    const patch = mockedSettingsApi.updateSettings.mock.calls[0][0];
    expect(patch.daily_time_budget_minutes?.monday).toBeNull();
  });

  it('shows an error banner when the save fails', async () => {
    mockedSettingsApi.updateSettings.mockRejectedValue(new ApiError(422, 'invalid_day_map', 'Bad day map.'));
    render(<SchedulingWindowSection settings={BASE_SETTINGS} onUpdated={vi.fn()} />);

    await userEvent.click(screen.getByRole('button', { name: /save scheduling window/i }));

    expect(await screen.findByText('Bad day map.')).toBeInTheDocument();
  });
});
