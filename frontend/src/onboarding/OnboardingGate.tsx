import { useEffect, useState, type ReactNode } from 'react';
import { Navigate } from 'react-router';
import { getSettings } from '../api/settings';

type GateState = 'checking' | 'open' | 'guide';

/** Sends a signed-in user to the setup guide (`/welcome`, design doc 8.1 screen 0a, Rev 16)
 * until it has been finished or skipped (`onboarding_completed`, 3.7). If the check itself
 * fails the app opens as usual: a missed guide is better than a locked-out user. */
export function OnboardingGate({ children }: { children: ReactNode }): JSX.Element | null {
  const [state, setState] = useState<GateState>('checking');

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((settings) => {
        if (!cancelled) setState(settings.onboarding_completed ? 'open' : 'guide');
      })
      .catch(() => {
        if (!cancelled) setState('open');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state === 'checking') return null;
  if (state === 'guide') return <Navigate to="/welcome" replace />;
  return <>{children}</>;
}
