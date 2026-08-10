import { apiClient } from './client';
import type { CalendarProvider, ExternalCalendarConnection } from '../types/calendarConnection';

/** `GET /calendar-connections` (design doc §3.5, §8.1 screen 6). */
export function listConnections(): Promise<ExternalCalendarConnection[]> {
  return apiClient.get<ExternalCalendarConnection[]>('/calendar-connections');
}

/** `GET /calendar-connections/{provider}/connect` - step 1 of the OAuth flow
 * (`backend/app/api/v1/routes/calendar_connections.py`). Returns the provider's
 * `authorize_url`; the caller is responsible for navigating the browser there
 * (`window.location.href = ...`), a real top-level cross-site navigation - this is
 * deliberately not a `<Link>`/client-side route. `refresh_interval_minutes` is set only
 * at connect time (there is no endpoint to change it on an already-connected calendar -
 * see `ExternalCalendarsSection`'s own note on why that's out of this stage's scope). */
export function connect(provider: CalendarProvider, refreshIntervalMinutes?: number): Promise<{ authorize_url: string }> {
  const query = refreshIntervalMinutes !== undefined ? `?refresh_interval_minutes=${refreshIntervalMinutes}` : '';
  return apiClient.get<{ authorize_url: string }>(`/calendar-connections/${provider}/connect${query}`);
}

/** `DELETE /calendar-connections/{connection_id}` - disconnect (§8.1 screen 6). */
export function disconnect(connectionId: string): Promise<void> {
  return apiClient.delete<void>(`/calendar-connections/${connectionId}`);
}
