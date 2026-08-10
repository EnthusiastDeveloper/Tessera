// Mirrors backend/app/db/schemas.py's `UserSettings`/`BlackoutDate` (architecture-plan
// §9's traceability rule). Originally added in Stage 9d for the Timeline's read-only
// `blackout_dates` need; the full Settings screen (Stage 9f, `src/views/settings/`)
// reads and writes every other field here too.

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
