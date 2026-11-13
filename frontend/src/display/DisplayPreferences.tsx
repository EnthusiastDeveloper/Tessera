import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { getSettings } from '../api/settings';
import { DEFAULT_DATE_FORMAT, DEFAULT_TIME_FORMAT, type DateFormat, type TimeFormat } from '../lib/dates';
import type { DayName } from '../types/task';
import type { UserSettings } from '../types/settings';

/** The display-only settings (design doc 3.7): how dates and times are written and where
 * the week starts. Loaded once for the signed-in app (`AppShell`) and updated in place when
 * Settings saves them, so no screen has to fetch settings just to format a date. */
export interface DisplayPreferences {
  dateFormat: DateFormat;
  timeFormat: TimeFormat;
  firstDayOfWeek: DayName;
}

const DEFAULTS: DisplayPreferences = {
  dateFormat: DEFAULT_DATE_FORMAT,
  timeFormat: DEFAULT_TIME_FORMAT,
  firstDayOfWeek: 'monday',
};

interface DisplayPreferencesValue {
  preferences: DisplayPreferences;
  applySettings: (settings: UserSettings) => void;
}

// Outside a provider (unit tests of a single screen) the defaults apply and updates are dropped.
const DisplayPreferencesContext = createContext<DisplayPreferencesValue>({
  preferences: DEFAULTS,
  applySettings: () => undefined,
});

function fromSettings(settings: UserSettings): DisplayPreferences {
  return {
    dateFormat: settings.date_format ?? DEFAULT_DATE_FORMAT,
    timeFormat: settings.time_format ?? DEFAULT_TIME_FORMAT,
    firstDayOfWeek: settings.first_day_of_week,
  };
}

export function DisplayPreferencesProvider({ children }: { children: ReactNode }): JSX.Element {
  const [preferences, setPreferences] = useState<DisplayPreferences>(DEFAULTS);

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((settings) => {
        if (!cancelled) setPreferences(fromSettings(settings));
      })
      // Formatting with the defaults beats failing a screen over a preference.
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo<DisplayPreferencesValue>(
    () => ({ preferences, applySettings: (settings) => setPreferences(fromSettings(settings)) }),
    [preferences]
  );

  return <DisplayPreferencesContext.Provider value={value}>{children}</DisplayPreferencesContext.Provider>;
}

export function useDisplayPreferences(): DisplayPreferences {
  return useContext(DisplayPreferencesContext).preferences;
}

/** For Settings: push a just-saved `UserSettings` so every screen picks it up at once. */
export function useApplyDisplaySettings(): (settings: UserSettings) => void {
  return useContext(DisplayPreferencesContext).applySettings;
}
