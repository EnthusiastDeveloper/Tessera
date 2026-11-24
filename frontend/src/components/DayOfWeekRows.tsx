import type { ReactNode } from 'react';
import type { DayName } from '../types/task';
import { useDisplayPreferences } from '../display/DisplayPreferences';
import { DAY_LABELS, daysOfWeekFrom } from '../lib/days';

interface DayOfWeekRowsProps {
  legend: string;
  hint?: string;
  /** One row per day of week, starting on the user's `first_day_of_week` (§3.7) - the caller supplies only the per-day control, this component owns the label/layout
   * repetition. Settings §8.1 screen 6 asks for this pattern twice (active-hours,
   * daily-budget); `ActiveHoursOverrideInput` (task form, §3.2) is a close cousin but a
   * genuinely different shape (partial map with an "inherit" state vs. these fields'
   * always-all-7-days map, §3.7), so it is left as its own component rather than forced
   * onto this one.
   */
  renderControl: (day: DayName) => ReactNode;
}

export function DayOfWeekRows({ legend, hint, renderControl }: DayOfWeekRowsProps): JSX.Element {
  const { firstDayOfWeek } = useDisplayPreferences();
  return (
    <fieldset className="field">
      <legend>{legend}</legend>
      {hint && (
        <p className="text-sm text-text-muted">{hint}</p>
      )}
      {daysOfWeekFrom(firstDayOfWeek).map((day) => (
        <div
          key={day}
          className="mb-2 flex items-center gap-2"
        >
          <span className="w-24 shrink-0">{DAY_LABELS[day]}</span>
          {renderControl(day)}
        </div>
      ))}
    </fieldset>
  );
}
