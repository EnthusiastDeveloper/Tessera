// Mirrors backend/app/db/schemas.py's `ExternalCalendarConnection` (design doc §3.5).

export type CalendarProvider = 'google' | 'outlook' | 'other';

export interface ExternalCalendarConnection {
  id: string;
  provider: CalendarProvider;
  oauth_credentials_ref: string;
  refresh_interval_minutes: number;
  last_synced_at?: string | null;
  sync_mode: 'read_only';
  enabled: boolean;
}
