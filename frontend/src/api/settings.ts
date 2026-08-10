import { apiClient } from './client';
import type { UserSettings } from '../types/settings';

/** `GET /settings` (design doc §3.7). Minimal for now - the Timeline (Stage 9d) only
 * needs `blackout_dates`; the full Settings screen (account, calendars, scheduling
 * window, timezone, display) is Stage 9f's job, not built here. */
export function getSettings(): Promise<UserSettings> {
  return apiClient.get<UserSettings>('/settings');
}
