import type { TimeFormat } from './dates';

/** Times of day as the API writes them ("17:30", 24-hour, zero-padded) and as the user reads
 * and types them in their `time_format` (design doc 3.7, Rev 15). Written here rather than
 * with `toLocaleTimeString`, because a field the user types into needs one exact spelling,
 * not whatever the browser's language prefers ("5:30 p.m.", "17 h 30"). */

const pad = (n: number): string => String(n).padStart(2, '0');

/** "17:30" -> "17:30" on a 24-hour clock, "5:30 PM" on a 12-hour one. "" stays "". */
export function formatClockTime(hhmm: string, timeFormat: TimeFormat): string {
  const match = /^(\d{2}):(\d{2})$/.exec(hhmm);
  if (!match) return '';
  if (timeFormat === '24h') return hhmm;
  const hour = Number(match[1]);
  const twelve = hour % 12 === 0 ? 12 : hour % 12;
  return `${twelve}:${match[2]} ${hour < 12 ? 'AM' : 'PM'}`;
}

/** What the user typed, as "HH:MM", or null if it isn't a time. Lenient whichever clock is
 * set: "17:30", "1730", "930", "17", "5:30pm", "5 PM", "5.30 p.m." and "12am" all read.
 * Without am/pm a number is read on the 24-hour clock ("5:30" is 05:30). */
export function parseTimeInput(text: string): string | null {
  const cleaned = text.trim().toLowerCase().replace(/[\s.]/g, '').replace(/(a|p)m?$/, (m) => ` ${m[0]}`);
  const match = /^(\d{1,2})(?::?(\d{2}))?(?: ([ap]))?$/.exec(cleaned.replace('h', ':'));
  if (!match) return null;
  let hour = Number(match[1]);
  const minute = match[2] === undefined ? 0 : Number(match[2]);
  const meridiem = match[3];
  if (minute > 59) return null;
  if (meridiem) {
    if (hour < 1 || hour > 12) return null;
    hour = (hour % 12) + (meridiem === 'p' ? 12 : 0);
  } else if (hour > 23) {
    return null;
  }
  return `${pad(hour)}:${pad(minute)}`;
}

/** Every `stepMinutes` of a day, "00:00" to "23:45" for 15. The time picker's list. */
export function timesOfDay(stepMinutes = 15): string[] {
  const times: string[] = [];
  for (let minutes = 0; minutes < 24 * 60; minutes += stepMinutes) {
    times.push(`${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`);
  }
  return times;
}

/** The list entry to show first: the value itself, or the step before it ("09:20" -> "09:15"). */
export function nearestStep(hhmm: string, stepMinutes = 15): string | null {
  const match = /^(\d{2}):(\d{2})$/.exec(hhmm);
  if (!match) return null;
  const minutes = Number(match[1]) * 60 + Number(match[2]);
  const floored = minutes - (minutes % stepMinutes);
  return `${pad(Math.floor(floored / 60))}:${pad(floored % 60)}`;
}

/** An instant as a local date and time of day ("2026-11-24", "17:30"), in the browser's zone,
 * as the old `datetime-local` fields read it. "" for none. */
export function splitLocalDateTime(iso: string | null | undefined): { date: string; time: string } {
  if (!iso) return { date: '', time: '' };
  const d = new Date(iso);
  return {
    date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
    time: `${pad(d.getHours())}:${pad(d.getMinutes())}`,
  };
}

/** The reverse: a local date and time to an ISO instant, or "" unless both are whole. */
export function joinLocalDateTime(date: string, time: string): string {
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  const t = /^(\d{2}):(\d{2})$/.exec(time);
  if (!d || !t) return '';
  return new Date(Number(d[1]), Number(d[2]) - 1, Number(d[3]), Number(t[1]), Number(t[2])).toISOString();
}
