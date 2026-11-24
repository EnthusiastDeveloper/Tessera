import { useState } from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TimeInput } from './TimeInput';
import { DateTimeInput } from './DateTimeInput';
import { DisplayPreferencesProvider } from '../display/DisplayPreferences';
import * as settingsApi from '../api/settings';
import type { UserSettings } from '../types/settings';

vi.mock('../api/settings');
const mockedSettingsApi = vi.mocked(settingsApi);

function useClock(timeFormat: '24h' | '12h'): void {
  mockedSettingsApi.getSettings.mockResolvedValue({ time_format: timeFormat, date_format: 'DD/MM/YYYY', first_day_of_week: 'sunday' } as UserSettings);
}

function TimeHarness({ initial = '', onChange }: { initial?: string; onChange?: (v: string) => void }): JSX.Element {
  const [value, setValue] = useState(initial);
  return (
    <DisplayPreferencesProvider>
      <label htmlFor="t">Time of day</label>
      <TimeInput
        id="t"
        value={value}
        onChange={(next) => {
          setValue(next);
          onChange?.(next);
        }}
      />
      <output data-testid="value">{value}</output>
      <button type="button" onClick={() => setValue('06:45')}>
        Set from outside
      </button>
    </DisplayPreferencesProvider>
  );
}

describe('TimeInput (design doc 8.1b, Rev 20)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useClock('24h');
  });

  it('writes the value on a 24-hour clock and reads what is typed', async () => {
    render(<TimeHarness initial="09:00" />);
    const field = screen.getByLabelText('Time of day');
    expect(field).toHaveValue('09:00');
    await userEvent.clear(field);
    await userEvent.type(field, '1730');
    expect(screen.getByTestId('value')).toHaveTextContent('17:30');
    await userEvent.tab();
    expect(field).toHaveValue('17:30');
  });

  it('follows a 12-hour setting, and still reads a 24-hour time typed into it', async () => {
    useClock('12h');
    render(<TimeHarness initial="17:30" />);
    const field = screen.getByLabelText('Time of day');
    await waitFor(() => expect(field).toHaveValue('5:30 PM'));
    await userEvent.clear(field);
    await userEvent.type(field, '21:15');
    await userEvent.tab();
    expect(field).toHaveValue('9:15 PM');
    expect(screen.getByTestId('value')).toHaveTextContent('21:15');
  });

  it('says so when what was typed is not a time, keeping the last good one', async () => {
    render(<TimeHarness initial="09:00" />);
    const field = screen.getByLabelText('Time of day');
    await userEvent.clear(field);
    await userEvent.type(field, '25:00');
    await userEvent.tab();
    expect(screen.getByText('Enter a time as HH:MM, e.g. 17:30.')).toBeInTheDocument();
    expect(field).toHaveAttribute('aria-invalid', 'true');
  });

  it('picks from a list of 15-minute steps, starting at the current time', async () => {
    const onChange = vi.fn();
    render(<TimeHarness initial="09:20" onChange={onChange} />);
    await userEvent.click(screen.getByRole('button', { name: 'Choose from a list of times' }));
    const list = await screen.findByRole('group', { name: 'Times' });
    expect(within(list).getAllByRole('button')).toHaveLength(96);
    expect(within(list).getByRole('button', { name: '09:15' })).toHaveFocus();
    await userEvent.keyboard('{ArrowDown}');
    expect(within(list).getByRole('button', { name: '09:30' })).toHaveFocus();
    await userEvent.keyboard('{Enter}');
    expect(onChange).toHaveBeenLastCalledWith('09:30');
    expect(screen.getByLabelText('Time of day')).toHaveValue('09:30');
    expect(screen.queryByRole('group', { name: 'Times' })).not.toBeInTheDocument();
  });

  it('follows a value set from outside', async () => {
    render(<TimeHarness initial="09:00" />);
    await userEvent.click(screen.getByRole('button', { name: 'Set from outside' }));
    expect(screen.getByLabelText('Time of day')).toHaveValue('06:45');
  });
});

describe('DateTimeInput', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useClock('24h');
  });

  function PairHarness({ initial, onChange }: { initial: string; onChange: (v: string) => void }): JSX.Element {
    const [value, setValue] = useState(initial);
    return (
      <DisplayPreferencesProvider>
        <label htmlFor="d">New deadline</label>
        <DateTimeInput
          id="d"
          label="New deadline"
          value={value}
          onChange={(next) => {
            setValue(next);
            onChange(next);
          }}
        />
      </DisplayPreferencesProvider>
    );
  }

  it('shows an instant as its local date and time, and changes either half', async () => {
    const onChange = vi.fn();
    render(<PairHarness initial={new Date(2026, 10, 24, 17, 30).toISOString()} onChange={onChange} />);
    expect(screen.getByLabelText('New deadline')).toHaveValue('24/11/2026');
    const time = screen.getByLabelText('New deadline time');
    expect(time).toHaveValue('17:30');
    await userEvent.clear(time);
    await userEvent.type(time, '0800');
    expect(onChange).toHaveBeenLastCalledWith(new Date(2026, 10, 24, 8, 0).toISOString());
    const date = screen.getByLabelText('New deadline');
    await userEvent.clear(date);
    await userEvent.type(date, '01/12/2026');
    expect(onChange).toHaveBeenLastCalledWith(new Date(2026, 11, 1, 8, 0).toISOString());
  });

  it('gives no instant while a half is missing', async () => {
    const onChange = vi.fn();
    render(<PairHarness initial={new Date(2026, 10, 24, 17, 30).toISOString()} onChange={onChange} />);
    await userEvent.clear(screen.getByLabelText('New deadline time'));
    expect(onChange).toHaveBeenLastCalledWith('');
  });
});
