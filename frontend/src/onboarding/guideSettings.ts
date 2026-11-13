import { DAY_ORDER } from '../lib/days';
import type { ActiveHoursWindow, DayName, DayWindows } from '../types/task';
import type { UserSettings } from '../types/settings';

/** The setup guide (design doc 8.1 screen 0a, Rev 16) asks simpler questions than
 * Settings does: which days, one set of hours for all of them, and one daily budget.
 * These helpers turn the stored per-day maps into those answers and back. */

export const DEFAULT_GUIDE_WINDOW: ActiveHoursWindow = { start: '09:00', end: '17:00' };

export interface GuideHours {
  days: DayName[];
  window: ActiveHoursWindow;
  /** False when the stored hours differ by day (or a day has several windows), which one
   * set of hours can't express - saving from the guide would make them all the same. */
  uniform: boolean;
}

function sameWindows(a: DayWindows | undefined, b: ActiveHoursWindow): boolean {
  return Array.isArray(a) && a.length === 1 && a[0].start === b.start && a[0].end === b.end;
}

export function readGuideHours(activeHours: UserSettings['active_hours']): GuideHours {
  const days = DAY_ORDER.filter((day) => Boolean(activeHours[day]));
  const first = days.length > 0 ? activeHours[days[0]] : null;
  const window = first?.[0] ?? DEFAULT_GUIDE_WINDOW;
  return { days, window, uniform: days.every((day) => sameWindows(activeHours[day], window)) };
}

/** The full 7-day map the API wants: the chosen days get the window, the rest are excluded. */
export function guideHoursToActiveHours(days: readonly DayName[], window: ActiveHoursWindow): Record<DayName, DayWindows> {
  return Object.fromEntries(
    DAY_ORDER.map((day) => [day, days.includes(day) ? [{ ...window }] : null])
  ) as Record<DayName, DayWindows>;
}

export interface GuideBudget {
  /** Minutes per day, or null for no limit. */
  minutes: number | null;
  uniform: boolean;
}

export function readGuideBudget(budget: UserSettings['daily_time_budget_minutes']): GuideBudget {
  const values = DAY_ORDER.map((day) => budget[day] ?? null);
  const distinct = new Set(values);
  if (distinct.size === 1) return { minutes: values[0], uniform: true };
  return { minutes: values.find((value) => value !== null) ?? null, uniform: false };
}

export function guideBudgetToDailyBudget(minutes: number | null): Record<DayName, number | null> {
  return Object.fromEntries(DAY_ORDER.map((day) => [day, minutes])) as Record<DayName, number | null>;
}
