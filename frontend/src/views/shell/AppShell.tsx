import { useEffect } from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../auth/AuthContext';
import { MosaicMark } from '../../components/MosaicMark';
import { ScheduleRepairOverlay } from '../../components/ScheduleRepairOverlay';
import { DisplayPreferencesProvider } from '../../display/DisplayPreferences';
import { AccountMenu } from './AccountMenu';
import { OptimizationDialogs } from '../../optimization/OptimizationDialogs';
import { OptimizationProvider, useOptimization } from '../../optimization/OptimizationContext';
import { OptimizingBanner } from '../../optimization/OptimizingBanner';
import type { CalendarProvider } from '../../types/calendarConnection';

const NAV_ITEMS = [
  { to: '/', label: 'Timeline', end: true },
  { to: '/backlog', label: 'Backlog' },
  { to: '/notifications', label: 'Notifications' },
  { to: '/settings', label: 'Settings' },
];

export function AppShell(): JSX.Element {
  return (
    <DisplayPreferencesProvider>
      <OptimizationProvider>
        <Shell />
      </OptimizationProvider>
    </DisplayPreferencesProvider>
  );
}

function Shell(): JSX.Element {
  const { user, logout } = useAuth();
  const { locked, showLockHint } = useOptimization();
  const location = useLocation();
  const navigate = useNavigate();

  // The OAuth callback (`backend/app/api/v1/routes/calendar_connections.py`) redirects
  // a real top-level browser navigation back to the app root with `?calendar_connected=
  // <provider>` - no frontend route consumed that query param until this stage built
  // Settings. Hand it off to `/settings` (via router state, not a persisted query
  // string) so `ExternalCalendarsSection` can show a one-time success banner, then drop
  // the query param from the URL so a later refresh doesn't re-trigger it.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const connectedProvider = params.get('calendar_connected') as CalendarProvider | null;
    if (connectedProvider) {
      navigate('/settings', { replace: true, state: { calendarConnected: connectedProvider } });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search]);

  return (
    <div>
      <header className="app-shell__bar">
        <Link to="/" className="mr-2 flex items-center gap-2.5 text-text no-underline hover:text-text">
          <MosaicMark />
          <span className="font-display text-lg font-bold tracking-tight">tessera</span>
        </Link>
        <nav className="app-shell__nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="flex-1" />
        <div className="flex items-center gap-3">
          {/* Read-only while an optimization runs (design doc §6.11): not a link then, and a click
              says why instead of doing nothing. */}
          {locked ? (
            <button type="button" className="primary" aria-disabled="true" onClick={showLockHint}>
              New task
            </button>
          ) : (
            <Link to="/tasks/new">
              <button type="button" className="primary">
                New task
              </button>
            </Link>
          )}
          <AccountMenu username={user?.username} onLogout={() => void logout()} />
        </div>
      </header>
      <main className="app-shell__content">
        <OptimizingBanner />
        <Outlet />
      </main>
      <ScheduleRepairOverlay />
      <OptimizationDialogs />
    </div>
  );
}
