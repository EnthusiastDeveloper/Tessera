import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { getSettings, markIntroductionSeen } from '../api/settings';

/** One-time introductions (design doc 3.7, 8.1, Rev 19): a short note that explains a
 * feature the first time it is met, until the user dismisses it. Which ones were dismissed
 * is kept on the server (`UserSettings.introductions_seen`), so each is shown once per
 * account, not once per device.
 *
 * Adding one for a new feature: pick a new key, add it to `IntroductionKey`, and render the
 * note while `useIntroduction(key).show` is true; call `dismiss` on its "Got it". No server
 * change is needed - an account that predates the feature simply hasn't seen the key yet, so
 * it gets the introduction once, like a new account. */
export type IntroductionKey = 'optimize_schedule';

interface IntroductionsValue {
  /** `null` until loaded: nothing is introduced before we know what was already seen. */
  seen: ReadonlySet<string> | null;
  dismiss: (key: IntroductionKey) => void;
}

// Outside a provider (a single screen in a unit test) nothing is introduced.
const IntroductionsContext = createContext<IntroductionsValue>({ seen: null, dismiss: () => undefined });

export function IntroductionsProvider({ children }: { children: ReactNode }): JSX.Element {
  const [seen, setSeen] = useState<ReadonlySet<string> | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((settings) => {
        if (!cancelled) setSeen(new Set(settings.introductions_seen ?? []));
      })
      // Unknown means "don't introduce": a note shown twice is worse than one not shown yet.
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const dismiss = useCallback((key: IntroductionKey) => {
    // Hidden at once; if saving fails it stays hidden for this visit and may return next time.
    setSeen((current) => new Set([...(current ?? []), key]));
    markIntroductionSeen(key).catch(() => undefined);
  }, []);

  const value = useMemo<IntroductionsValue>(() => ({ seen, dismiss }), [seen, dismiss]);
  return <IntroductionsContext.Provider value={value}>{children}</IntroductionsContext.Provider>;
}

export function useIntroduction(key: IntroductionKey): { show: boolean; dismiss: () => void } {
  const { seen, dismiss } = useContext(IntroductionsContext);
  return { show: seen !== null && !seen.has(key), dismiss: () => dismiss(key) };
}
