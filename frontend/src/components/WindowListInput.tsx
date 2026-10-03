import type { ActiveHoursWindow } from '../types/task';
import { MAX_WINDOWS_PER_DAY } from '../lib/limits';

const NEW_WINDOW: ActiveHoursWindow = { start: '18:00', end: '21:00' };

interface WindowListInputProps {
  /** "Monday" - used to label each control for assistive tech and tests. */
  dayLabel: string;
  windows: ActiveHoursWindow[];
  onChange: (windows: ActiveHoursWindow[]) => void;
}

/** One day's list of active-hours windows (design doc §3.7, Rev 13): a start and end per
 * window, "Add window", and "Remove" once there is more than one. An `end` earlier than
 * its `start` is an overnight window, ending the next morning, and is labelled as such.
 * The last window can't be removed - a day with none is "Excluded", which the caller's
 * mode select expresses. Overlap and zero-length windows are the server's check. */
export function WindowListInput({
  dayLabel,
  windows,
  onChange,
}: WindowListInputProps): JSX.Element {
  const update = (index: number, change: Partial<ActiveHoursWindow>): void => {
    onChange(windows.map((window, i) => (i === index ? { ...window, ...change } : window)));
  };
  const labelFor = (index: number, part: 'start' | 'end'): string =>
    index === 0 ? `${dayLabel} ${part}` : `${dayLabel} window ${index + 1} ${part}`;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
      {windows.map((window, index) => (
        <div key={index} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <input
            type="time"
            aria-label={labelFor(index, 'start')}
            value={window.start}
            onChange={(event) => update(index, { start: event.target.value })}
          />
          <span>to</span>
          <input
            type="time"
            aria-label={labelFor(index, 'end')}
            value={window.end}
            onChange={(event) => update(index, { end: event.target.value })}
          />
          {window.end < window.start && (
            <span style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)' }}>
              (ends next day)
            </span>
          )}
          {windows.length > 1 && (
            <button
              type="button"
              onClick={() => onChange(windows.filter((_, i) => i !== index))}
              aria-label={`Remove ${dayLabel} window ${index + 1}`}
            >
              Remove
            </button>
          )}
        </div>
      ))}
      <div>
        <button
          type="button"
          disabled={windows.length >= MAX_WINDOWS_PER_DAY}
          onClick={() => onChange([...windows, NEW_WINDOW])}
          aria-label={`Add ${dayLabel} window`}
        >
          Add window
        </button>
      </div>
    </div>
  );
}
