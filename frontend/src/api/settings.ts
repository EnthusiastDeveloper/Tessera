import { apiClient } from './client';
import type { UserSettings } from '../types/settings';

/** `GET /settings` (design doc §3.7). */
export function getSettings(): Promise<UserSettings> {
  return apiClient.get<UserSettings>('/settings');
}

/** `PATCH /settings` - genuinely partial (`backend/app/api/v1/routes/settings.py`'s own
 * docstring: only keys present in the request body are applied). `active_hours` and
 * `daily_time_budget_minutes` are the two exceptions worth calling out: the backend
 * validates them as a *complete* 7-day map whenever the key is present at all
 * (`_validate_full_week`) - so a caller changing even one day must still send all 7. */
export function updateSettings(patch: Partial<UserSettings>): Promise<UserSettings> {
  return apiClient.patch<UserSettings>('/settings', patch);
}
