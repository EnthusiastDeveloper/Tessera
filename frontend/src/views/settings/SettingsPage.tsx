import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { getSettings } from '../../api/settings';
import { ApiError, toApiError } from '../../api/client';
import type { CalendarProvider } from '../../types/calendarConnection';
import type { UserSettings } from '../../types/settings';
import { AccountSection } from './AccountSection';
import { ExternalCalendarsSection } from './ExternalCalendarsSection';
import { SchedulingWindowSection } from './SchedulingWindowSection';
import { TimezoneSection } from './TimezoneSection';
import { DisplaySection } from './DisplaySection';

type LoadState = 'loading' | 'error' | 'ready';

interface SettingsRouteState {
  calendarConnected?: CalendarProvider;
}

/** §8.1 screen 6 - the five Settings sections: Account (change password), External
 * calendars (OAuth connect UI), Scheduling window, Timezone, Display. Account and
 * External calendars don't depend on `UserSettings` (§3.6/§3.5 are separate entities),
 * so they render immediately; the other three share one `GET /settings` fetch and each
 * saves independently via its own `PATCH /settings` call, reporting the server's
 * response back up through `onUpdated` so a later section's save always patches onto
 * the most current row rather than a stale one read before an earlier section's save
 * landed.
 */
export function SettingsPage(): JSX.Element {
  const location = useLocation();
  const [state, setState] = useState<LoadState>('loading');
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const routeState = location.state as SettingsRouteState | null;

  useEffect(() => {
    getSettings()
      .then((loaded) => {
        setSettings(loaded);
        setState('ready');
      })
      .catch((err: unknown) => {
        setError(toApiError(err));
        setState('error');
      });
  }, []);

  return (
    <div>
      <h2>Settings</h2>

      <AccountSection />
      <ExternalCalendarsSection justConnectedProvider={routeState?.calendarConnected ?? null} />

      {state === 'loading' && <p>Loading…</p>}
      {state === 'error' && (
        <div className="banner-error" role="alert">
          {error?.message ?? 'Could not load settings.'}
        </div>
      )}
      {state === 'ready' && settings && (
        <>
          <SchedulingWindowSection settings={settings} onUpdated={setSettings} />
          <TimezoneSection settings={settings} onUpdated={setSettings} />
          <DisplaySection settings={settings} onUpdated={setSettings} />
        </>
      )}
    </div>
  );
}
