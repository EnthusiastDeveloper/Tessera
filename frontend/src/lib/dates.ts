/** How dates and times are written everywhere in the UI (design doc 3.7, `date_format` and
 * `time_format`; display only).
 *
 * Every date the app shows goes through this module, never `toLocaleString()` - the
 * browser's locale would otherwise decide the order of day and month (an en-US browser
 * writes 13 November as 11/13) and the clock (12- or 24-hour).
 *
 * Dates are formatted in the device's own timezone, like the rest of the UI (the
 * Timeline flags a device/setting mismatch, design doc 14.1).
 */

export type DateFormat = 'DD/MM/YYYY' | 'MM/DD/YYYY' | 'YYYY-MM-DD';

export type TimeFormat = '24h' | '12h';

export const DEFAULT_DATE_FORMAT: DateFormat = 'DD/MM/YYYY';
export const DEFAULT_TIME_FORMAT: TimeFormat = '24h';

/** Settings choices, each with an example so the user sees the order, not just letters. */
export const DATE_FORMAT_OPTIONS: ReadonlyArray<{ value: DateFormat; label: string }> = [
  { value: 'DD/MM/YYYY', label: 'Day first - 31/12/2026' },
  { value: 'MM/DD/YYYY', label: 'Month first - 12/31/2026' },
  { value: 'YYYY-MM-DD', label: 'Year first (ISO) - 2026-12-31' },
];

export const TIME_FORMAT_OPTIONS: ReadonlyArray<{ value: TimeFormat; label: string }> = [
  { value: '24h', label: '24-hour - 17:30' },
  { value: '12h', label: '12-hour - 5:30 PM' },
];

type DateInput = Date | string;

function toDate(value: DateInput): Date {
  return value instanceof Date ? value : new Date(value);
}

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

/** "13/11/2026", "11/13/2026" or "2026-11-13". */
export function formatDate(value: DateInput, format: DateFormat): string {
  const d = toDate(value);
  const dd = pad(d.getDate());
  const mm = pad(d.getMonth() + 1);
  const yyyy = String(d.getFullYear());
  if (format === 'MM/DD/YYYY') return `${mm}/${dd}/${yyyy}`;
  if (format === 'YYYY-MM-DD') return `${yyyy}-${mm}-${dd}`;
  return `${dd}/${mm}/${yyyy}`;
}

/** The same without the year, for places where the year is obvious: "13/11", "11/13", "11-13". */
export function formatDayMonth(value: DateInput, format: DateFormat): string {
  const d = toDate(value);
  const dd = pad(d.getDate());
  const mm = pad(d.getMonth() + 1);
  if (format === 'MM/DD/YYYY') return `${mm}/${dd}`;
  if (format === 'YYYY-MM-DD') return `${mm}-${dd}`;
  return `${dd}/${mm}`;
}

/** Short weekday in the browser's language: "Fri". */
export function formatWeekday(value: DateInput): string {
  return toDate(value).toLocaleDateString(undefined, { weekday: 'short' });
}

/** Hours and minutes: "08:44" / "17:30" on a 24-hour clock, "8:44 AM" / "5:30 PM" on 12. */
export function formatTime(value: DateInput, timeFormat: TimeFormat = DEFAULT_TIME_FORMAT): string {
  return toDate(value).toLocaleTimeString(undefined, {
    hour: timeFormat === '24h' ? '2-digit' : 'numeric',
    minute: '2-digit',
    hourCycle: timeFormat === '24h' ? 'h23' : 'h12',
  });
}

/** "13/11/2026 08:44" - a full timestamp (history, notifications, last sync). */
export function formatDateTime(
  value: DateInput,
  format: DateFormat,
  timeFormat: TimeFormat = DEFAULT_TIME_FORMAT
): string {
  return `${formatDate(value, format)} ${formatTime(value, timeFormat)}`;
}

/** "Fri 13/11" - a day in the near future or past, where the year goes without saying. */
export function formatWeekdayDayMonth(value: DateInput, format: DateFormat): string {
  return `${formatWeekday(value)} ${formatDayMonth(value, format)}`;
}

/** "Fri 13/11 08:44" - a moment in the near future or past. */
export function formatWeekdayDayMonthTime(
  value: DateInput,
  format: DateFormat,
  timeFormat: TimeFormat = DEFAULT_TIME_FORMAT
): string {
  return `${formatWeekdayDayMonth(value, format)} ${formatTime(value, timeFormat)}`;
}

/** A calendar date as the API sends it ("2026-11-13", no time or zone) in the user's
 * format. Split by hand: `new Date("2026-11-13")` is midnight UTC, which is the previous
 * day anywhere west of Greenwich. Empty in, empty out. */
export function formatIsoDate(iso: string, format: DateFormat): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return '';
  const [, yyyy, mm, dd] = match;
  if (format === 'MM/DD/YYYY') return `${mm}/${dd}/${yyyy}`;
  if (format === 'YYYY-MM-DD') return iso;
  return `${dd}/${mm}/${yyyy}`;
}

function daysInMonth(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

/** What the user typed in a date field, as an API date ("2026-11-13"), or null if it isn't
 * a real date yet. Reads day and month in the order of their `format`; "/", "." and "-"
 * all separate, and leading zeros are optional ("4/5/2026"). A year-first ISO date is
 * always accepted too, so a pasted "2026-11-13" works whatever the format. */
export function parseDateInput(text: string, format: DateFormat): string | null {
  const trimmed = text.trim();
  let year: number;
  let month: number;
  let day: number;
  const yearFirst = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/.exec(trimmed);
  const yearLast = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/.exec(trimmed);
  if (yearFirst) {
    [year, month, day] = yearFirst.slice(1).map(Number);
  } else if (yearLast) {
    const [first, second, y] = yearLast.slice(1).map(Number);
    year = y;
    [day, month] = format === 'MM/DD/YYYY' ? [second, first] : [first, second];
  } else {
    return null;
  }
  if (month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) return null;
  return `${year}-${pad(month)}-${pad(day)}`;
}
