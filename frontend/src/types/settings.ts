// Mirrors backend/app/db/schemas.py's `UserSettings`/`BlackoutDate` (architecture-plan
// §9's traceability rule). The full Settings screen is Stage 9f - this stage only needs
// `blackout_dates` (Timeline display, design doc §8.1 screen 2), but the type mirrors the
// whole wire shape rather than a hand-picked subset, matching every other type in this
// directory.

import type { ActiveHoursWindow, DayName } from './task';

export interface BlackoutDate {
  start: string; // "YYYY-MM-DD"
  end: string;
  label?: string | null;
}

export type BudgetEnforcement = 'strict' | 'soft';

export interface UserSettings {
  id: string;
  timezone: string;
  active_hours: Partial<Record<DayName, ActiveHoursWindow | null>>;
  blackout_dates: BlackoutDate[];
  daily_time_budget_minutes: Partial<Record<DayName, number | null>>;
  budget_enforcement: BudgetEnforcement;
  first_day_of_week: DayName;
}
