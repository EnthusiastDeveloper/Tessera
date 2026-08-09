import { Navigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useAuth } from '../auth/AuthContext';
import type { AuthStatus } from '../auth/AuthContext';

const REDIRECT_FOR: Record<Exclude<AuthStatus, 'loading'>, string> = {
  setup_required: '/setup',
  unauthenticated: '/login',
  authenticated: '/',
};

/** Renders `children` only when the current auth status is in `allow`; otherwise
 * redirects to whichever screen the current status actually belongs on. This is the
 * mechanism behind design doc §8.1 screen 0's "every other screen redirects here until
 * one does" - applied uniformly to every route group, not just the setup screen. */
export function RouteGuard({
  allow,
  children,
}: {
  allow: AuthStatus[];
  children: ReactNode;
}): JSX.Element | null {
  const { status } = useAuth();

  if (status === 'loading') {
    return null;
  }
  if (!allow.includes(status)) {
    return <Navigate to={REDIRECT_FOR[status]} replace />;
  }
  return <>{children}</>;
}
