import type { DayName } from '../types/task';

/** The seven days in a fixed Monday-first order - the order the API and the data model
 * key every day map in (design doc §3.7's `active_hours`/`daily_time_budget_minutes`,
 * §3.2's `active_hours_override`). Controls don't show days in this order: they show the
 * user's week, `daysOfWeekFrom(first_day_of_week)` (§3.7: the setting sets "the row order
 * of the day-of-week settings"). It is display only - every day map is keyed by name, so
 * reordering rows changes nothing that is saved. */
export const DAY_ORDER: readonly DayName[] = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
];

export const DAY_LABELS: Record<DayName, string> = {
  monday: 'Monday',
  tuesday: 'Tuesday',
  wednesday: 'Wednesday',
  thursday: 'Thursday',
  friday: 'Friday',
  saturday: 'Saturday',
  sunday: 'Sunday',
};

/** The week as the user sees it, starting on their `first_day_of_week`:
 * `daysOfWeekFrom('sunday')` is Sunday, Monday, ..., Saturday. */
export function daysOfWeekFrom(first: DayName): DayName[] {
  const start = DAY_ORDER.indexOf(first);
  return [...DAY_ORDER.slice(start), ...DAY_ORDER.slice(0, start)];
}
