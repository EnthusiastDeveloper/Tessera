import { useCallback, useEffect, useState } from 'react';
import { connect as connectProvider, disconnect as disconnectConnection, listConnections } from '../../api/calendarConnections';
import { ApiError } from '../../api/client';
import type { CalendarProvider, ExternalCalendarConnection } from '../../types/calendarConnection';

type LoadState = 'loading' | 'error' | 'ready';

// registry.py: only these two providers have a real POC implementation - "other" is in
// the `CalendarProvider` enum (design doc §3.5) but rejected at connect time with
// `provider_not_configured`, so no button offers it.
const CONNECTABLE_PROVIDERS: CalendarProvider[] = ['google', 'outlook'];

const PROVIDER_LABELS: Record<CalendarProvider, string> = {
  google: 'Google Calendar',
  outlook: 'Outlook Calendar',
  other: 'Other',
};

function formatLastSynced(lastSyncedAt: string | null | undefined): string {
  if (!lastSyncedAt) return 'Never synced';
  return `Last synced: ${new Date(lastSyncedAt).toLocaleString()}`;
}

interface ExternalCalendarsSectionProps {
  /** Set by `SettingsPage` when the browser just landed back from a real OAuth redirect
   * (`?calendar_connected=<provider>` - see `backend/app/api/v1/routes/calendar_
   * connections.py`'s callback endpoint). One-shot: shown once, not re-derived from the
   * URL by this component itself. */
  justConnectedProvider?: CalendarProvider | null;
}

/** §8.1 screen 6 "External calendars: connect/disconnect, refresh interval, last-sync
 * timestamp." (design doc §3.5, §7).
 *
 * **Scope decision for `refresh_interval_minutes` (documented per this stage's own
 * instruction not to leave it implicit):** shown read-only with a note, not editable.
 * `GET /{provider}/connect` only accepts it as a query param at connect time
 * (`backend/app/api/v1/routes/calendar_connections.py`) - there is no endpoint to
 * change it on an already-connected calendar, and screen 6's own design doc bullet
 * only says the interval is *shown*, not that it's editable post-connect. Disconnect-
 * and-reconnect is the documented path to change it, matching what the backend actually
 * exposes rather than inventing a new PATCH endpoint this stage doesn't otherwise need.
 */
export function ExternalCalendarsSection({ justConnectedProvider }: ExternalCalendarsSectionProps): JSX.Element {
  const [state, setState] = useState<LoadState>('loading');
  const [connections, setConnections] = useState<ExternalCalendarConnection[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [connectingProvider, setConnectingProvider] = useState<CalendarProvider | null>(null);
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);

  const load = useCallback(() => {
    setState('loading');
    setError(null);
    listConnections()
      .then((loaded) => {
        setConnections(loaded);
        setState('ready');
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err : new ApiError(0, 'network_error', 'Could not reach the server.'));
        setState('error');
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleConnect = async (provider: CalendarProvider): Promise<void> => {
    setError(null);
    setConnectingProvider(provider);
    try {
      const { authorize_url: authorizeUrl } = await connectProvider(provider);
      // Real top-level navigation, not a client-side route - this leaves the SPA
      // entirely for the provider's own login/consent screen and comes back via the
      // backend's callback redirect (see `justConnectedProvider` above).
      window.location.href = authorizeUrl;
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, 'network_error', 'Could not reach the server.'));
      setConnectingProvider(null);
    }
  };

  const handleDisconnect = async (connectionId: string): Promise<void> => {
    setError(null);
    setDisconnectingId(connectionId);
    try {
      await disconnectConnection(connectionId);
      setConnections((prev) => prev.filter((connection) => connection.id !== connectionId));
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, 'network_error', 'Could not reach the server.'));
    } finally {
      setDisconnectingId(null);
    }
  };

  return (
    <section className="settings-section">
      <h3>External calendars</h3>

      {justConnectedProvider && (
        <div className="banner-success" role="status">
          {PROVIDER_LABELS[justConnectedProvider]} connected.
        </div>
      )}
      {error && (
        <div className="banner-error" role="alert">
          {error.message}
        </div>
      )}

      {state === 'loading' && <p>Loading…</p>}

      {state !== 'loading' && (
        <>
          {connections.length === 0 ? (
            <p style={{ color: 'var(--color-text-muted)' }}>No calendars connected.</p>
          ) : (
            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
              {connections.map((connection) => (
                <li
                  key={connection.id}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: 'var(--space-4)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 'var(--radius)',
                    padding: 'var(--space-3) var(--space-4)',
                    marginBottom: 'var(--space-2)',
                  }}
                >
                  <div>
                    <strong>{PROVIDER_LABELS[connection.provider]}</strong>
                    {!connection.enabled && <span style={{ color: 'var(--color-text-muted)' }}> (disabled)</span>}
                    <p style={{ margin: 'var(--space-1) 0 0', color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)' }}>
                      {formatLastSynced(connection.last_synced_at)} · Refresh interval:{' '}
                      {connection.refresh_interval_minutes} minutes (disconnect and reconnect to change)
                    </p>
                  </div>
                  <button
                    type="button"
                    className="danger"
                    disabled={disconnectingId === connection.id}
                    onClick={() => void handleDisconnect(connection.id)}
                  >
                    {disconnectingId === connection.id ? 'Disconnecting…' : 'Disconnect'}
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-4)' }}>
            {CONNECTABLE_PROVIDERS.map((provider) => (
              <button
                key={provider}
                type="button"
                disabled={connectingProvider === provider}
                onClick={() => void handleConnect(provider)}
              >
                {connectingProvider === provider ? 'Connecting…' : `Connect ${PROVIDER_LABELS[provider]}`}
              </button>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
