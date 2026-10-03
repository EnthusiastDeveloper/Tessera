import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { DurationInput } from './DurationInput';

describe('DurationInput max (design doc §3.13)', () => {
  it('expresses the minute cap in whichever unit is selected', async () => {
    render(
      <DurationInput
        id="d"
        label="Estimated duration"
        initialMinutes={60}
        units={['hours', 'minutes']}
        onChange={() => undefined}
        min={1}
        maxMinutes={1440}
      />
    );

    expect(screen.getByLabelText('Estimated duration')).toHaveAttribute('max', '24');
    await userEvent.selectOptions(screen.getByLabelText('Estimated duration unit'), 'minutes');
    expect(screen.getByLabelText('Estimated duration')).toHaveAttribute('max', '1440');
  });
});
