import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { DayOfWeekRows } from './DayOfWeekRows';
import { DisplayPreferencesProvider } from '../display/DisplayPreferences';
import * as settingsApi from '../api/settings';
import type { UserSettings } from '../types/settings';

vi.mock('../api/settings');

const mockedSettingsApi = vi.mocked(settingsApi);

function rowLabels(): string[] {
  return screen.getAllByTestId('day-control').map((el) => el.getAttribute('data-day') ?? '');
}

function renderRows(): void {
  render(
    <DisplayPreferencesProvider>
      <DayOfWeekRows legend="Active hours" renderControl={(day) => <span data-testid="day-control" data-day={day} />} />
    </DisplayPreferencesProvider>
  );
}

describe('DayOfWeekRows', () => {
  it('starts on Sunday by default', () => {
    mockedSettingsApi.getSettings.mockReturnValue(new Promise(() => undefined));
    renderRows();
    expect(rowLabels()[0]).toBe('sunday');
    expect(rowLabels()[6]).toBe('saturday');
  });

  it("follows the user's first day of the week", async () => {
    mockedSettingsApi.getSettings.mockResolvedValue({ first_day_of_week: 'monday' } as UserSettings);
    renderRows();
    await waitFor(() => expect(rowLabels()[0]).toBe('monday'));
    expect(rowLabels()[6]).toBe('sunday');
  });
});
