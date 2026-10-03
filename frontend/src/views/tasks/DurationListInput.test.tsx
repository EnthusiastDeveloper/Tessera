import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DurationListInput } from './DurationListInput';

describe('DurationListInput reminder cap (design doc §3.13)', () => {
  it('stops offering "Add reminder" at ten reminders', () => {
    const { rerender } = render(
      <DurationListInput label="Reminders" values={[15, 30]} onChange={() => undefined} />
    );
    expect(screen.getByRole('button', { name: 'Add reminder' })).toBeEnabled();

    rerender(
      <DurationListInput
        label="Reminders"
        values={Array.from({ length: 10 }, (_, i) => (i + 1) * 5)}
        onChange={() => undefined}
      />
    );
    expect(screen.getByRole('button', { name: 'Add reminder' })).toBeDisabled();
  });
});
