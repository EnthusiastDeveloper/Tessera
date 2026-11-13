import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { SetupGuide } from './SetupGuide';
import * as settingsApi from '../api/settings';
import type { UserSettings } from '../types/settings';

vi.mock('../api/settings');

const mockedSettingsApi = vi.mocked(settingsApi);

// This test environment has no Web Storage; the guide only needs get/set/remove.
const storage = new Map<string, string>();
Object.defineProperty(window, 'localStorage', {
  configurable: true,
  value: {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => void storage.set(key, value),
    removeItem: (key: string) => void storage.delete(key),
    clear: () => storage.clear(),
  },
});

const NINE_TO_FIVE = [{ start: '09:00', end: '17:00' }];

const SETTINGS: UserSettings = {
  id: 'settings-1',
  timezone: 'UTC',
  active_hours: {
    sunday: NINE_TO_FIVE,
    monday: NINE_TO_FIVE,
    tuesday: NINE_TO_FIVE,
    wednesday: NINE_TO_FIVE,
    thursday: NINE_TO_FIVE,
    friday: NINE_TO_FIVE,
    saturday: NINE_TO_FIVE,
  },
  blackout_dates: [],
  daily_time_budget_minutes: {
    sunday: null,
    monday: null,
    tuesday: null,
    wednesday: null,
    thursday: null,
    friday: null,
    saturday: null,
  },
  budget_enforcement: 'soft',
  first_day_of_week: 'sunday',
  date_format: 'DD/MM/YYYY',
  time_format: '24h',
  onboarding_completed: false,
};

function renderGuide(state?: { restart: boolean }): void {
  render(
    <MemoryRouter initialEntries={[{ pathname: '/welcome', state }]}>
      <Routes>
        <Route path="/welcome" element={<SetupGuide />} />
        <Route path="/" element={<p>The Timeline</p>} />
        <Route path="/tasks/new" element={<p>New task form</p>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('SetupGuide', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    mockedSettingsApi.getSettings.mockResolvedValue(SETTINGS);
    mockedSettingsApi.updateSettings.mockImplementation((patch) => Promise.resolve({ ...SETTINGS, ...patch }));
    mockedSettingsApi.getScheduleRepair.mockResolvedValue(null);
  });

  it('walks every step, saving each one, and records that the guide is done at the end', async () => {
    const user = userEvent.setup();
    renderGuide();

    expect(await screen.findByRole('heading', { name: 'Your timezone' })).toBeInTheDocument();
    expect(screen.getByText('Step 1 of 4')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(mockedSettingsApi.updateSettings).toHaveBeenLastCalledWith({ timezone: 'UTC' }));

    expect(await screen.findByRole('heading', { name: 'Your week' })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText('First day of the week'), 'monday');
    await user.selectOptions(screen.getByLabelText('Time format'), '12h');
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() =>
      expect(mockedSettingsApi.updateSettings).toHaveBeenLastCalledWith({
        first_day_of_week: 'monday',
        date_format: 'DD/MM/YYYY',
        time_format: '12h',
      })
    );

    expect(await screen.findByRole('heading', { name: 'When should Tessera schedule tasks?' })).toBeInTheDocument();
    // The first step that depends on it explains fixed vs flexible before asking.
    expect(screen.getByText('Fixed')).toBeInTheDocument();
    expect(screen.getByText('Flexible')).toBeInTheDocument();
    // The week the user just chose: Monday first.
    expect(screen.getAllByRole('button', { pressed: true })[0]).toHaveAccessibleName('Monday');
    await user.click(screen.getByRole('button', { name: 'Saturday' }));
    await user.click(screen.getByRole('button', { name: 'Sunday' }));
    await user.click(screen.getByRole('button', { name: /^Evenings/ }));
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(mockedSettingsApi.updateSettings).toHaveBeenCalledTimes(3));
    const hours = mockedSettingsApi.updateSettings.mock.calls[2][0].active_hours;
    expect(hours?.monday).toEqual([{ start: '18:00', end: '22:00' }]);
    expect(hours?.saturday).toBeNull();
    expect(hours?.sunday).toBeNull();

    expect(await screen.findByRole('heading', { name: 'How much in one day?' })).toBeInTheDocument();
    await user.click(screen.getByLabelText('Set a limit'));
    await user.click(screen.getByLabelText(/Stick to the limit/));
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(mockedSettingsApi.updateSettings).toHaveBeenCalledTimes(4));
    const last = mockedSettingsApi.updateSettings.mock.calls[3][0];
    expect(last.onboarding_completed).toBe(true);
    expect(last.budget_enforcement).toBe('strict');
    expect(last.daily_time_budget_minutes?.monday).toBe(240);

    expect(await screen.findByRole('heading', { name: "That's it" })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Add your first task' }));
    expect(await screen.findByText('New task form')).toBeInTheDocument();
  });

  it('skips a step without saving it, and goes back', async () => {
    const user = userEvent.setup();
    renderGuide();
    await screen.findByRole('heading', { name: 'Your timezone' });
    await user.click(screen.getByRole('button', { name: 'Skip' }));
    expect(await screen.findByRole('heading', { name: 'Your week' })).toBeInTheDocument();
    expect(mockedSettingsApi.updateSettings).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Back' }));
    expect(await screen.findByRole('heading', { name: 'Your timezone' })).toBeInTheDocument();
  });

  it('won\'t save hours with no day chosen', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem('tessera.setupGuide.step', '2');
    renderGuide();
    await screen.findByRole('heading', { name: 'When should Tessera schedule tasks?' });
    for (const day of ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']) {
      await user.click(screen.getByRole('button', { name: day }));
    }
    expect(screen.getByText('Pick at least one day.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
  });

  it('skipping the whole setup records it and opens the Timeline', async () => {
    const user = userEvent.setup();
    renderGuide();
    await screen.findByRole('heading', { name: 'Your timezone' });
    await user.click(screen.getByRole('button', { name: 'Skip setup' }));
    expect(await screen.findByText('The Timeline')).toBeInTheDocument();
    expect(mockedSettingsApi.updateSettings).toHaveBeenCalledWith({ onboarding_completed: true });
  });

  it('picks up at the step reached', async () => {
    window.localStorage.setItem('tessera.setupGuide.step', '1');
    renderGuide();
    expect(await screen.findByRole('heading', { name: 'Your week' })).toBeInTheDocument();
  });

  it('starts from the top when run again from Settings', async () => {
    window.localStorage.setItem('tessera.setupGuide.step', '1');
    renderGuide({ restart: true });
    expect(await screen.findByRole('heading', { name: 'Your timezone' })).toBeInTheDocument();
  });

  it('warns that saving evens out hours that differ by day', async () => {
    mockedSettingsApi.getSettings.mockResolvedValue({
      ...SETTINGS,
      active_hours: { ...SETTINGS.active_hours, friday: [{ start: '08:00', end: '13:00' }] },
    });
    window.localStorage.setItem('tessera.setupGuide.step', '2');
    renderGuide();
    expect(await screen.findByText(/Your days don't all have the same hours/)).toBeInTheDocument();
  });

  it('shows the server\'s error and stays on the step', async () => {
    const user = userEvent.setup();
    mockedSettingsApi.updateSettings.mockRejectedValue(new Error('offline'));
    renderGuide();
    await screen.findByRole('heading', { name: 'Your timezone' });
    await user.click(screen.getByRole('button', { name: 'Continue' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach the server.');
    expect(screen.getByRole('heading', { name: 'Your timezone' })).toBeInTheDocument();
  });
});
