import type { ActiveHoursOverride, ActiveHoursWindow, DayName } from '../../types/task';

const DAYS: DayName[] = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];
const DAY_LABELS: Record<DayName, string> = {
  monday: 'Monday',
  tuesday: 'Tuesday',
  wednesday: 'Wednesday',
  thursday: 'Thursday',
  friday: 'Friday',
  saturday: 'Saturday',
  sunday: 'Sunday',
};
const DEFAULT_WINDOW: ActiveHoursWindow = { start: '09:00', end: '17:00' };

type DayMode = 'inherit' | 'excluded' | 'custom';

function modeFor(window: ActiveHoursWindow | null | undefined): DayMode {
  if (window === undefined) return 'inherit';
  if (window === null) return 'excluded';
  return 'custom';
}

interface ActiveHoursOverrideInputProps {
  value: ActiveHoursOverride | null | undefined;
  onChange: (value: ActiveHoursOverride | null) => void;
}

/** Design doc §3.2's per-template override, merging over `UserSettings.active_hours`
 * (§3.7) - a day not named here inherits the global map; a day named `null` is
 * excluded, identically to §3.7's own rule (never "unrestricted" - that's an explicit
 * 00:00-23:59 window instead). */
export function ActiveHoursOverrideInput({ value, onChange }: ActiveHoursOverrideInputProps): JSX.Element {
  const emit = (day: DayName, mode: DayMode, window?: ActiveHoursWindow): void => {
    const next: ActiveHoursOverride = { ...(value ?? {}) };
    if (mode === 'inherit') {
      delete next[day];
    } else if (mode === 'excluded') {
      next[day] = null;
    } else {
      next[day] = window ?? next[day] ?? DEFAULT_WINDOW;
    }
    onChange(Object.keys(next).length === 0 ? null : next);
  };

  return (
    <fieldset className="field">
      <legend>Active-hours override</legend>
      <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)' }}>
        Days left as &quot;Inherit&quot; use your global scheduling-window settings.
      </p>
      {DAYS.map((day) => {
        const dayValue = value?.[day];
        const mode = modeFor(dayValue);
        return (
          <div
            key={day}
            style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-2)' }}
          >
            <span style={{ width: '6rem' }}>{DAY_LABELS[day]}</span>
            <select
              aria-label={`${DAY_LABELS[day]} active hours`}
              value={mode}
              onChange={(event) => emit(day, event.target.value as DayMode)}
            >
              <option value="inherit">Inherit</option>
              <option value="excluded">Excluded</option>
              <option value="custom">Custom</option>
            </select>
            {mode === 'custom' && (
              <>
                <input
                  type="time"
                  aria-label={`${DAY_LABELS[day]} start`}
                  value={dayValue?.start ?? DEFAULT_WINDOW.start}
                  onChange={(event) =>
                    emit(day, 'custom', { start: event.target.value, end: dayValue?.end ?? DEFAULT_WINDOW.end })
                  }
                />
                <span>to</span>
                <input
                  type="time"
                  aria-label={`${DAY_LABELS[day]} end`}
                  value={dayValue?.end ?? DEFAULT_WINDOW.end}
                  onChange={(event) =>
                    emit(day, 'custom', { start: dayValue?.start ?? DEFAULT_WINDOW.start, end: event.target.value })
                  }
                />
              </>
            )}
          </div>
        );
      })}
    </fieldset>
  );
}
