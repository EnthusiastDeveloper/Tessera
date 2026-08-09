import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import * as authApi from '../api/auth';
import { ApiError } from '../api/client';
import type { User } from '../types/auth';

/**
 * `setup_required` and `unauthenticated` are genuinely distinct states (design doc §8.1
 * screen 0): the backend's auth guard tells us which one we're in via a dedicated error
 * code on every request, not just a generic 401 - see backend/app/api/middleware.py's
 * `SETUP_ALLOWED_ROUTES`. This is what lets the frontend redirect correctly no matter
 * which URL loads first, without a bespoke "does an account exist" endpoint.
 */
export type AuthStatus = 'loading' | 'setup_required' | 'unauthenticated' | 'authenticated';

export interface AuthContextValue {
  status: AuthStatus;
  user: User | null;
  /** True for the one render cycle after setup completes and before the user logs in -
   * lets the login screen greet them, without relying on router-navigation state that
   * races against this same status transition (see `completeSetup`). */
  justCompletedSetup: boolean;
  completeSetup: (token: string, password: string) => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }): JSX.Element {
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [user, setUser] = useState<User | null>(null);
  const [justCompletedSetup, setJustCompletedSetup] = useState(false);

  useEffect(() => {
    let cancelled = false;
    authApi
      .me()
      .then((fetchedUser) => {
        if (cancelled) return;
        setUser(fetchedUser);
        setStatus('authenticated');
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.code === 'setup_required') {
          setStatus('setup_required');
        } else {
          setStatus('unauthenticated');
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const completeSetup = useCallback(async (token: string, password: string) => {
    // Setup only creates the account (backend/app/api/v1/routes/auth.py never sets a
    // session cookie there) - the user still logs in afterwards on the login screen.
    // RouteGuard does the actual redirect once `status` flips (see RouteGuard.tsx) -
    // this function must not also navigate imperatively, or the two redirects race.
    await authApi.setup(token, password);
    setStatus('unauthenticated');
    setJustCompletedSetup(true);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const loggedInUser = await authApi.login(username, password);
    setUser(loggedInUser);
    setStatus('authenticated');
    setJustCompletedSetup(false);
  }, []);

  const logout = useCallback(async () => {
    await authApi.logout();
    setUser(null);
    setStatus('unauthenticated');
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, justCompletedSetup, completeSetup, login, logout }),
    [status, user, justCompletedSetup, completeSetup, login, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
