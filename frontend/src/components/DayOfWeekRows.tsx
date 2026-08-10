import type { ReactNode } from 'react';
import type { DayName } from '../types/task';
import { DAY_LABELS, DAY_ORDER } from '../lib/days';

interface DayOfWeekRowsProps {
  legend: string;
  hint?: string;
  /** One row per day of week, in canonical Monday-first order (§3.7's own field order) -
   * the caller supplies only the per-day control, this component owns the label/layout
   * repetition. Settings §8.1 screen 6 asks for this pattern twice (active-hours,
   * daily-budget); `ActiveHoursOverrideInput` (task form, §3.2) is a close cousin but a
   * genuinely different shape (partial map with an "inherit" state vs. these fields'
   * always-all-7-days map, §3.7), so it is left as its own component rather than forced
   * onto this one.
   */
  renderControl: (day: DayName) => ReactNode;
}

export function DayOfWeekRows({ legend, hint, renderControl }: DayOfWeekRowsProps): JSX.Element {
  return (
    <fieldset className="field">
      <legend>{legend}</legend>
      {hint && (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)' }}>{hint}</p>
      )}
      {DAY_ORDER.map((day) => (
        <div
          key={day}
          style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-2)' }}
        >
          <span style={{ width: '6rem' }}>{DAY_LABELS[day]}</span>
          {renderControl(day)}
        </div>
      ))}
    </fieldset>
  );
}
