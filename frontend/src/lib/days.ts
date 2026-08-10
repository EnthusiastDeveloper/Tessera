import type { DayName } from '../types/task';

/** Canonical Monday-first day-of-week order and display labels, shared by every
 * per-day-of-week control (design doc §3.7's `active_hours`/`daily_time_budget_minutes`,
 * §3.2's `active_hours_override`). `first_day_of_week` (§3.7) is display-only for the
 * Timeline/Settings *ordering*, not this list - see design doc's own note that it "does
 * not affect the algorithm"; every day-map field is keyed identically regardless. */
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
