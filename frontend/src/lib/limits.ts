/** Field limits - mirror backend/app/api/v1/validation.py (design doc §3.13, IRR-2 M11).
 * The server is the authority; these only keep the form from offering what it will refuse. */
export const MAX_NAME_LENGTH = 200;
export const MAX_DESCRIPTION_LENGTH = 2000;
export const MAX_LOCATION_LENGTH = 200;
export const MAX_DURATION_MINUTES = 24 * 60;
export const MAX_RECURRENCE_INTERVAL = 365;
export const MAX_DEADLINE_OFFSET_MINUTES = 365 * 24 * 60;
export const MAX_REMINDER_OFFSETS = 10;
export const MAX_REMINDER_OFFSET_MINUTES = 30 * 24 * 60;
export const MAX_DAILY_BUDGET_MINUTES = 24 * 60;
export const MAX_BLACKOUT_LABEL_LENGTH = 100;
