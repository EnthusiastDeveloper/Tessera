import { useEffect } from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../../auth/AuthContext';
import type { CalendarProvider } from '../../types/calendarConnection';

const NAV_ITEMS = [
  { to: '/', label: 'Timeline', end: true },
  { to: '/backlog', label: 'Backlog' },
  { to: '/notifications', label: 'Notifications' },
  { to: '/settings', label: 'Settings' },
];

export function AppShell(): JSX.Element {
  const { user, logout } = useAuth();
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
        <strong>Tessera</strong>
        <nav className="app-shell__nav">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div>
          <Link to="/tasks/new" style={{ marginRight: 'var(--space-4)' }}>
            <button type="button" className="primary">
              New task
            </button>
          </Link>
          <span style={{ marginRight: 'var(--space-4)', color: 'var(--color-text-muted)' }}>
            {user?.username}
          </span>
          <button type="button" onClick={() => void logout()}>
            Log out
          </button>
        </div>
      </header>
      <main className="app-shell__content">
        <Outlet />
      </main>
    </div>
  );
}
