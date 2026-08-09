import type { DurationUnit } from '../../lib/duration';
import { REMINDER_OFFSET_UNITS, durationToMinutes, minutesToDuration } from '../../lib/duration';

type ReminderUnit = DurationUnit | 'at_start';

const UNIT_OPTION_LABELS: Record<DurationUnit, string> = {
  minutes: 'minutes before',
  hours: 'hours before',
  days: 'days before',
  weeks: 'weeks before',
};

const DEFAULT_NEW_REMINDER_MINUTES = 15;

function unitOf(minutes: number): ReminderUnit {
  return minutes === 0 ? 'at_start' : minutesToDuration(minutes, REMINDER_OFFSET_UNITS).unit;
}

function amountOf(minutes: number): number {
  return minutes === 0 ? 0 : minutesToDuration(minutes, REMINDER_OFFSET_UNITS).value;
}

interface DurationListInputProps {
  label: string;
  values: number[];
  onChange: (values: number[]) => void;
}

/** Reminder offsets (design doc §3.2 `reminder_offsets_minutes`) - a list of "before
 * scheduled_time" durations, plus the explicit "at start time" option §8.1a requires
 * for zero (never a bare "0 minutes before"). */
export function DurationListInput({ label, values, onChange }: DurationListInputProps): JSX.Element {
  const updateAt = (index: number, minutes: number): void => {
    onChange(values.map((v, i) => (i === index ? minutes : v)));
  };
  const removeAt = (index: number): void => {
    onChange(values.filter((_, i) => i !== index));
  };

  return (
    <fieldset className="field">
      <legend>{label}</legend>
      {values.length === 0 && <p style={{ color: 'var(--color-text-muted)' }}>No reminders set.</p>}
      {values.map((minutes, index) => {
        const unit = unitOf(minutes);
        return (
          <div key={index} style={{ display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-2)' }}>
            {unit !== 'at_start' && (
              <input
                type="number"
                min={0}
                step="any"
                aria-label={`Reminder ${index + 1} value`}
                value={amountOf(minutes)}
                onChange={(event) => {
                  const parsed = Number.parseFloat(event.target.value);
                  updateAt(index, durationToMinutes(Number.isFinite(parsed) ? parsed : 0, unit as DurationUnit));
                }}
              />
            )}
            <select
              aria-label={`Reminder ${index + 1} unit`}
              value={unit}
              onChange={(event) => {
                const nextUnit = event.target.value as ReminderUnit;
                if (nextUnit === 'at_start') {
                  updateAt(index, 0);
                } else {
                  updateAt(index, durationToMinutes(amountOf(minutes) || DEFAULT_NEW_REMINDER_MINUTES, nextUnit));
                }
              }}
            >
              <option value="at_start">At start time</option>
              {REMINDER_OFFSET_UNITS.map((u) => (
                <option key={u} value={u}>
                  {UNIT_OPTION_LABELS[u]}
                </option>
              ))}
            </select>
            <button type="button" onClick={() => removeAt(index)} aria-label={`Remove reminder ${index + 1}`}>
              Remove
            </button>
          </div>
        );
      })}
      <button type="button" onClick={() => onChange([...values, DEFAULT_NEW_REMINDER_MINUTES])}>
        Add reminder
      </button>
    </fieldset>
  );
}
