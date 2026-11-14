import { useEffect, useRef, useState } from 'react';
import { useDisplayPreferences } from '../display/DisplayPreferences';
import { formatIsoDate, parseDateInput } from '../lib/dates';

interface DateInputProps {
  /** The text field's id, for the caller's `<label htmlFor>`. */
  id: string;
  /** An API date ("2026-11-13"), or "" for none. */
  value: string;
  onChange: (value: string) => void;
  min?: string;
  max?: string;
  required?: boolean;
}

function CalendarIcon(): JSX.Element {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="2" y="3" width="12" height="11" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <path
        d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** A date field in the user's `date_format` (design doc 3.7). The browser's own
 * `<input type="date">` writes dates in the browser's language, so an en-US browser shows
 * 11/13/2026 whatever the setting says. This is a text field in the user's format instead,
 * with a button that opens the browser's calendar for picking with the mouse.
 *
 * Typing updates `value` as soon as the text is a whole, real date; until then the last
 * good date stands. Leaving the field with something that isn't one says so beside it. */
export function DateInput({
  id,
  value,
  onChange,
  min,
  max,
  required = false,
}: DateInputProps): JSX.Element {
  const { dateFormat } = useDisplayPreferences();
  const [text, setText] = useState(() => formatIsoDate(value, dateFormat));
  const [error, setError] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  // Follow changes made elsewhere: another field that sets this one, or a new date format.
  // Text that already means `value` is left alone, so typing "4/5/2026" isn't rewritten
  // mid-keystroke (it is tidied up on blur).
  useEffect(() => {
    if (parseDateInput(text, dateFormat) !== value) setText(formatIsoDate(value, dateFormat));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, dateFormat]);

  const outOfRange = (iso: string): string | null => {
    if (min && iso < min) return `Pick ${formatIsoDate(min, dateFormat)} or later.`;
    if (max && iso > max) return `Pick ${formatIsoDate(max, dateFormat)} or earlier.`;
    return null;
  };

  const handleChange = (raw: string): void => {
    setText(raw);
    setError(null);
    if (raw.trim() === '') {
      onChange('');
      return;
    }
    const iso = parseDateInput(raw, dateFormat);
    if (iso) onChange(iso);
  };

  const handleBlur = (): void => {
    if (text.trim() === '') return;
    const iso = parseDateInput(text, dateFormat);
    if (!iso) {
      setError(`Enter a date as ${dateFormat}.`);
      return;
    }
    setText(formatIsoDate(iso, dateFormat));
    setError(outOfRange(iso));
  };

  const openCalendar = (): void => {
    const input = picker.current;
    if (!input) return;
    try {
      input.showPicker();
    } catch {
      // No showPicker (older browsers): focusing and clicking the field opens it there.
      input.focus();
      input.click();
    }
  };

  const errorId = `${id}-error`;
  return (
    <div>
      <div className="relative flex max-w-60 items-center gap-2">
        <input
          id={id}
          type="text"
          inputMode="numeric"
          autoComplete="off"
          placeholder={dateFormat}
          value={text}
          required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          onChange={(event) => handleChange(event.target.value)}
          onBlur={handleBlur}
        />
        <button
          type="button"
          className="shrink-0 px-2.5"
          aria-label="Choose from a calendar"
          onClick={openCalendar}
        >
          <CalendarIcon />
        </button>
        {/* The browser's calendar, opened by the button. Kept in the layout (not
            display:none) because showPicker() refuses a hidden input and anchors to it. */}
        <input
          ref={picker}
          type="date"
          tabIndex={-1}
          aria-hidden="true"
          className="pointer-events-none absolute bottom-0 right-0 size-px opacity-0"
          value={value}
          min={min}
          max={max}
          onChange={(event) => {
            onChange(event.target.value);
            setText(formatIsoDate(event.target.value, dateFormat));
            setError(event.target.value ? outOfRange(event.target.value) : null);
          }}
        />
      </div>
      {error && (
        <p id={errorId} className="field-error">
          {error}
        </p>
      )}
    </div>
  );
}
