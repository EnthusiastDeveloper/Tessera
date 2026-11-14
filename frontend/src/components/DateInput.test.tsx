import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DateInput } from './DateInput';
import { DisplayPreferencesProvider } from '../display/DisplayPreferences';
import * as settingsApi from '../api/settings';
import type { UserSettings } from '../types/settings';

vi.mock('../api/settings');

const mockedSettingsApi = vi.mocked(settingsApi);

function Harness({
  initial = '',
  min,
  onChange,
}: {
  initial?: string;
  min?: string;
  onChange?: (v: string) => void;
}): JSX.Element {
  const [value, setValue] = useState(initial);
  return (
    <>
      <label htmlFor="d">When</label>
      <DateInput
        id="d"
        value={value}
        min={min}
        onChange={(next) => {
          setValue(next);
          onChange?.(next);
        }}
      />
      <button type="button" onClick={() => setValue('2026-01-31')}>
        Set from outside
      </button>
    </>
  );
}

describe('DateInput', () => {
  it('shows the date day first by default', () => {
    render(<Harness initial="2026-03-02" />);
    expect(screen.getByLabelText('When')).toHaveValue('02/03/2026');
    expect(screen.getByLabelText('When')).toHaveAttribute('placeholder', 'DD/MM/YYYY');
  });

  it('reports a typed date once it is whole, and tidies it on blur', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const field = screen.getByLabelText('When');
    await userEvent.type(field, '4/5/2026');
    expect(onChange).toHaveBeenLastCalledWith('2026-05-04');
    expect(field).toHaveValue('4/5/2026');
    fireEvent.blur(field);
    expect(field).toHaveValue('04/05/2026');
  });

  it('says so when the text is not a date', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const field = screen.getByLabelText('When');
    await userEvent.type(field, '31/02/2026');
    fireEvent.blur(field);
    expect(screen.getByText('Enter a date as DD/MM/YYYY.')).toBeInTheDocument();
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(onChange).not.toHaveBeenCalledWith(expect.stringMatching(/^2026-02/));
  });

  it('flags a date before the minimum', async () => {
    render(<Harness min="2026-06-01" />);
    const field = screen.getByLabelText('When');
    await userEvent.type(field, '01/05/2026');
    fireEvent.blur(field);
    expect(screen.getByText('Pick 01/06/2026 or later.')).toBeInTheDocument();
  });

  it('follows a value set from outside', async () => {
    render(<Harness initial="2026-03-02" />);
    await userEvent.click(screen.getByRole('button', { name: 'Set from outside' }));
    expect(screen.getByLabelText('When')).toHaveValue('31/01/2026');
  });

  it('takes a date picked from the calendar', () => {
    const onChange = vi.fn();
    const { container } = render(<Harness onChange={onChange} />);
    const calendar = container.querySelector('input[type="date"]') as HTMLInputElement;
    fireEvent.change(calendar, { target: { value: '2026-12-24' } });
    expect(onChange).toHaveBeenLastCalledWith('2026-12-24');
    expect(screen.getByLabelText('When')).toHaveValue('24/12/2026');
  });

  it("uses the user's month-first format when they chose it", async () => {
    mockedSettingsApi.getSettings.mockResolvedValue({
      date_format: 'MM/DD/YYYY',
      first_day_of_week: 'sunday',
    } as UserSettings);
    render(
      <DisplayPreferencesProvider>
        <Harness initial="2026-03-02" />
      </DisplayPreferencesProvider>
    );
    await waitFor(() => expect(screen.getByLabelText('When')).toHaveValue('03/02/2026'));
  });
});
