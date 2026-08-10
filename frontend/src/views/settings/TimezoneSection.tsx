import { useState } from 'react';
import { updateSettings } from '../../api/settings';
import { ApiError } from '../../api/client';
import type { UserSettings } from '../../types/settings';

// `Intl.supportedValuesOf` (ES2022) isn't in this project's `tsconfig.json` `lib`
// (ES2020, kept narrow deliberately elsewhere in this codebase) - declared locally
// rather than widening `lib` for the whole app over one call.
declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Intl {
    function supportedValuesOf(key: string): string[];
  }
}

/** IANA timezone names available in this runtime (`Intl.supportedValuesOf`, Node 18+ /
 * every evergreen browser) - the same source of truth the backend validates against
 * (`zoneinfo.ZoneInfo`, `app.settings.service._validate_timezone`), so every option this
 * select offers is guaranteed valid rather than a hand-maintained list that can drift. */
function availableTimezones(): string[] {
  if (typeof Intl.supportedValuesOf === 'function') {
    return Intl.supportedValuesOf('timeZone');
  }
  return ['UTC'];
}

interface TimezoneSectionProps {
  settings: UserSettings;
  onUpdated: (settings: UserSettings) => void;
}

/** §8.1 screen 6 "Timezone: select IANA timezone, defaulted from container TZ" (§3.7,
 * §14.1). Fixed tasks re-project on a timezone change unless `detached` (§14.1) -
 * that's server-side behavior triggered automatically by this same `PATCH /settings`
 * call, nothing extra for this component to do.
 */
export function TimezoneSection({ settings, onUpdated }: TimezoneSectionProps): JSX.Element {
  const [timezone, setTimezone] = useState(settings.timezone);
  const [bannerError, setBannerError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [timezones] = useState<string[]>(availableTimezones);

  const handleSave = async (): Promise<void> => {
    setBannerError(null);
    setSuccessMessage(null);
    setSaving(true);
    try {
      const updated = await updateSettings({ timezone });
      onUpdated(updated);
      setSuccessMessage('Timezone saved.');
    } catch (err) {
      setBannerError(err instanceof ApiError ? err.message : 'Could not reach the server.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="settings-section">
      <h3>Timezone</h3>
      {bannerError && (
        <div className="banner-error" role="alert">
          {bannerError}
        </div>
      )}
      {successMessage && (
        <div className="banner-success" role="status">
          {successMessage}
        </div>
      )}
      <div className="field">
        <label htmlFor="settings-timezone">Timezone</label>
        <select id="settings-timezone" value={timezone} onChange={(event) => setTimezone(event.target.value)}>
          {!timezones.includes(timezone) && <option value={timezone}>{timezone}</option>}
          {timezones.map((tz) => (
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </select>
      </div>
      <button type="button" className="primary" disabled={saving} onClick={() => void handleSave()}>
        {saving ? 'Saving…' : 'Save timezone'}
      </button>
    </section>
  );
}
