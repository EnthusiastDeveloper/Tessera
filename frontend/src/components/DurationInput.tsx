import { useState } from 'react';
import type { DurationUnit } from '../lib/duration';
import { durationToMinutes, minutesToDuration } from '../lib/duration';

const UNIT_LABELS: Record<DurationUnit, string> = {
  minutes: 'minutes',
  hours: 'hours',
  days: 'days',
  weeks: 'weeks',
};

interface DurationInputProps {
  id: string;
  label: string;
  /** Seeds the control's initial value/unit only - this component is uncontrolled
   * after mount (design doc §8.1a's input is a number + unit pair, not a live-synced
   * minutes value). Remount with a `key` change if the caller needs to reset it to a
   * different task's value. */
  initialMinutes: number;
  units: readonly DurationUnit[];
  onChange: (minutes: number) => void;
  min?: number;
}

export function DurationInput({ id, label, initialMinutes, units, onChange, min = 0 }: DurationInputProps): JSX.Element {
  const initial = minutesToDuration(initialMinutes, units);
  const [rawValue, setRawValue] = useState(String(initial.value));
  const [unit, setUnit] = useState<DurationUnit>(initial.unit);

  const emit = (nextRawValue: string, nextUnit: DurationUnit): void => {
    const parsed = Number.parseFloat(nextRawValue);
    onChange(durationToMinutes(Number.isFinite(parsed) ? parsed : 0, nextUnit));
  };

  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
        <input
          id={id}
          type="number"
          min={min}
          step="any"
          value={rawValue}
          onChange={(event) => {
            setRawValue(event.target.value);
            emit(event.target.value, unit);
          }}
        />
        <select
          aria-label={`${label} unit`}
          value={unit}
          onChange={(event) => {
            const nextUnit = event.target.value as DurationUnit;
            setUnit(nextUnit);
            emit(rawValue, nextUnit);
          }}
        >
          {units.map((u) => (
            <option key={u} value={u}>
              {UNIT_LABELS[u]}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
