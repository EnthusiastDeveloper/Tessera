import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../../auth/AuthContext';

const NAV_ITEMS = [
  { to: '/', label: 'Timeline', end: true },
  { to: '/backlog', label: 'Backlog' },
  { to: '/notifications', label: 'Notifications' },
  { to: '/settings', label: 'Settings' },
];

export function AppShell(): JSX.Element {
  const { user, logout } = useAuth();

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
