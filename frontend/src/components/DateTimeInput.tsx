import { useEffect, useState } from 'react';
import { joinLocalDateTime, splitLocalDateTime } from '../lib/times';
import { DateInput } from './DateInput';
import { TimeInput } from './TimeInput';

interface DateTimeInputProps {
  /** The date field's id, for the caller's `<label htmlFor>`; the time field is `${id}-time`. */
  id: string;
  /** What the pair is, for the time field's own name ("New deadline" -> "New deadline time"). */
  label: string;
  /** An ISO instant, or "" for none. */
  value: string;
  onChange: (value: string) => void;
  min?: string;
}

/** A moment: a date in the user's `date_format` beside a time on their clock (design doc
 * 8.1b, Rev 20), replacing `<input type="datetime-local">`, which follows the browser's
 * language for both. Read in the browser's zone, as that field was. `value` changes only
 * when both halves are whole; picking a date alone keeps the time already there. */
export function DateTimeInput({ id, label, value, onChange, min }: DateTimeInputProps): JSX.Element {
  const [parts, setParts] = useState(() => splitLocalDateTime(value));

  // A new value from outside (not one this pair just produced) replaces both halves.
  useEffect(() => {
    if (joinLocalDateTime(parts.date, parts.time) !== value) setParts(splitLocalDateTime(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const update = (next: { date: string; time: string }): void => {
    setParts(next);
    onChange(joinLocalDateTime(next.date, next.time));
  };

  return (
    <div className="flex flex-wrap items-start gap-2">
      <DateInput id={id} value={parts.date} min={min} onChange={(date) => update({ ...parts, date })} />
      <TimeInput
        id={`${id}-time`}
        aria-label={`${label} time`}
        value={parts.time}
        onChange={(time) => update({ ...parts, time })}
      />
    </div>
  );
}
