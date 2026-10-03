import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ActiveHoursOverrideInput } from './ActiveHoursOverrideInput';

describe('ActiveHoursOverrideInput (design doc §3.2, Rev 13)', () => {
  it('turns a day custom with one default window, then lets it take a second overnight one', async () => {
    const onChange = vi.fn();
    const { rerender } = render(<ActiveHoursOverrideInput value={null} onChange={onChange} />);

    await userEvent.selectOptions(screen.getByLabelText('Friday active hours'), 'custom');
    expect(onChange).toHaveBeenLastCalledWith({ friday: [{ start: '09:00', end: '17:00' }] });

    rerender(
      <ActiveHoursOverrideInput
        value={{ friday: [{ start: '09:00', end: '17:00' }] }}
        onChange={onChange}
      />
    );
    await userEvent.click(screen.getByRole('button', { name: 'Add Friday window' }));
    expect(onChange).toHaveBeenLastCalledWith({
      friday: [
        { start: '09:00', end: '17:00' },
        { start: '18:00', end: '21:00' },
      ],
    });

    rerender(
      <ActiveHoursOverrideInput
        value={{
          friday: [
            { start: '09:00', end: '17:00' },
            { start: '22:00', end: '02:00' },
          ],
        }}
        onChange={onChange}
      />
    );
    expect(screen.getByText('(ends next day)')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Friday window 2 end'), { target: { value: '03:00' } });
    expect(onChange).toHaveBeenLastCalledWith({
      friday: [
        { start: '09:00', end: '17:00' },
        { start: '22:00', end: '03:00' },
      ],
    });
  });

  it('names an excluded day with null and drops an inherited one', async () => {
    const onChange = vi.fn();
    render(
      <ActiveHoursOverrideInput
        value={{ monday: [{ start: '08:00', end: '12:00' }] }}
        onChange={onChange}
      />
    );

    await userEvent.selectOptions(screen.getByLabelText('Monday active hours'), 'excluded');
    expect(onChange).toHaveBeenLastCalledWith({ monday: null });
    await userEvent.selectOptions(screen.getByLabelText('Monday active hours'), 'inherit');
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});
