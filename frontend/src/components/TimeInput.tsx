import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import * as Popover from '@radix-ui/react-popover';
import { useDisplayPreferences } from '../display/DisplayPreferences';
import { formatClockTime, nearestStep, parseTimeInput, timesOfDay } from '../lib/times';

interface TimeInputProps {
  /** The text field's id, for the caller's `<label htmlFor>`; generated when it has none. */
  id?: string;
  /** "HH:MM" on the 24-hour clock, as the API writes it, or "" for none. */
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  /** An accessible name when no `<label>` points at the field (e.g. the end of a window). */
  'aria-label'?: string;
  disabled?: boolean;
}

const STEPS = timesOfDay(15);

function ClockIcon(): JSX.Element {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="6.25" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8 4.5V8l2.5 1.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

/** A time of day in the user's `time_format` (design doc 3.7, 8.1b, Rev 20). The browser's
 * `<input type="time">` follows the browser's language, so a 12-hour browser shows "05:30 PM"
 * whatever the setting says. This is a text field written on the user's clock instead -
 * "17:30" or "5:30 PM" - that reads either spelling when typed, with a button that opens a
 * list of times in 15-minute steps (the scheduling grid, 6.2) for picking with the mouse.
 *
 * Typing updates `value` as soon as the text is a whole time; leaving the field with
 * something that isn't one says so beside it. */
export function TimeInput({
  id: givenId,
  value,
  onChange,
  required = false,
  'aria-label': ariaLabel,
  disabled = false,
}: TimeInputProps): JSX.Element {
  const generatedId = useId();
  const id = givenId ?? generatedId;
  const { timeFormat } = useDisplayPreferences();
  const [text, setText] = useState(() => formatClockTime(value, timeFormat));
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const list = useRef<HTMLDivElement>(null);

  // Follow changes made elsewhere (a prefill, another field), but leave text that already
  // means `value` alone so "530pm" isn't rewritten mid-keystroke. A new clock setting always
  // rewrites it: "17:30" still means 17:30 on a 12-hour clock, but should read "5:30 PM".
  const shownFormat = useRef(timeFormat);
  useEffect(() => {
    const clockChanged = shownFormat.current !== timeFormat;
    shownFormat.current = timeFormat;
    if (clockChanged || parseTimeInput(text) !== value) setText(formatClockTime(value, timeFormat));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, timeFormat]);

  const handleChange = (raw: string): void => {
    setText(raw);
    setError(null);
    if (raw.trim() === '') {
      onChange('');
      return;
    }
    const parsed = parseTimeInput(raw);
    if (parsed) onChange(parsed);
  };

  const handleBlur = (): void => {
    if (text.trim() === '') return;
    const parsed = parseTimeInput(text);
    if (!parsed) {
      setError(timeFormat === '24h' ? 'Enter a time as HH:MM, e.g. 17:30.' : 'Enter a time like 5:30 PM.');
      return;
    }
    setText(formatClockTime(parsed, timeFormat));
  };

  const pick = (time: string): void => {
    onChange(time);
    setText(formatClockTime(time, timeFormat));
    setError(null);
    setOpen(false);
  };

  // Arrow keys walk the list; Home/End jump to its ends. Escape is Radix's.
  const handleListKey = (event: KeyboardEvent<HTMLDivElement>): void => {
    const buttons = Array.from(list.current?.querySelectorAll<HTMLButtonElement>('button') ?? []);
    const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const target =
      event.key === 'ArrowDown'
        ? buttons[Math.min(at + 1, buttons.length - 1)]
        : event.key === 'ArrowUp'
          ? buttons[Math.max(at - 1, 0)]
          : event.key === 'Home'
            ? buttons[0]
            : event.key === 'End'
              ? buttons[buttons.length - 1]
              : undefined;
    if (!target) return;
    event.preventDefault();
    target.focus();
    target.scrollIntoView?.({ block: 'nearest' });
  };

  const start = nearestStep(value) ?? '09:00';
  const errorId = `${id}-error`;
  return (
    <div>
      <div className="flex max-w-44 items-center gap-2">
        <input
          id={id}
          type="text"
          autoComplete="off"
          placeholder={timeFormat === '24h' ? 'HH:MM' : 'h:mm AM'}
          value={text}
          required={required}
          disabled={disabled}
          aria-label={ariaLabel}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          onChange={(event) => handleChange(event.target.value)}
          onBlur={handleBlur}
        />
        <Popover.Root open={open} onOpenChange={setOpen}>
          <Popover.Trigger asChild>
            <button
              type="button"
              className="shrink-0 px-2.5"
              aria-label="Choose from a list of times"
              disabled={disabled}
            >
              <ClockIcon />
            </button>
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Content
              className="time-picker"
              align="end"
              sideOffset={4}
              collisionPadding={8}
              onOpenAutoFocus={(event) => {
                // Start on the current time (or 09:00), not the top of the day.
                event.preventDefault();
                const selected = list.current?.querySelector<HTMLButtonElement>(`[data-time="${start}"]`);
                selected?.focus();
                selected?.scrollIntoView?.({ block: 'center' });
              }}
            >
              <div ref={list} role="group" aria-label="Times" className="time-picker__list" onKeyDown={handleListKey}>
                {STEPS.map((time) => (
                  <button
                    key={time}
                    type="button"
                    data-time={time}
                    aria-pressed={time === value}
                    className="time-picker__item"
                    onClick={() => pick(time)}
                  >
                    {formatClockTime(time, timeFormat)}
                  </button>
                ))}
              </div>
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      </div>
      {error && (
        <p id={errorId} className="field-error">
          {error}
        </p>
      )}
    </div>
  );
}
