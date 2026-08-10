import { useState } from 'react';
import { updateSettings } from '../../api/settings';
import { ApiError } from '../../api/client';
import { DAY_LABELS, DAY_ORDER } from '../../lib/days';
import type { UserSettings } from '../../types/settings';

interface DisplaySectionProps {
  settings: UserSettings;
  onUpdated: (settings: UserSettings) => void;
}

/** §8.1 screen 6 "Display: first day of the week (for Timeline layout and Settings
 * ordering)." Display-only (§3.7: "doesn't affect the algorithm") - this section exists
 * purely to let the user pick which weekday any per-day-of-week list in the UI starts
 * from; it has no effect on scheduling.
 */
export function DisplaySection({ settings, onUpdated }: DisplaySectionProps): JSX.Element {
  const [firstDayOfWeek, setFirstDayOfWeek] = useState(settings.first_day_of_week);
  const [bannerError, setBannerError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const handleSave = async (): Promise<void> => {
    setBannerError(null);
    setSuccessMessage(null);
    setSaving(true);
    try {
      const updated = await updateSettings({ first_day_of_week: firstDayOfWeek });
      onUpdated(updated);
      setSuccessMessage('Display preference saved.');
    } catch (err) {
      setBannerError(err instanceof ApiError ? err.message : 'Could not reach the server.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="settings-section">
      <h3>Display</h3>
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
        <label htmlFor="first-day-of-week">First day of the week</label>
        <select
          id="first-day-of-week"
          value={firstDayOfWeek}
          onChange={(event) => setFirstDayOfWeek(event.target.value as UserSettings['first_day_of_week'])}
        >
          {DAY_ORDER.map((day) => (
            <option key={day} value={day}>
              {DAY_LABELS[day]}
            </option>
          ))}
        </select>
      </div>
      <button type="button" className="primary" disabled={saving} onClick={() => void handleSave()}>
        {saving ? 'Saving…' : 'Save display preference'}
      </button>
    </section>
  );
}
