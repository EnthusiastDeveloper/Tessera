import { useState } from 'react';
import { updateSettings } from '../../api/settings';
import { ApiError } from '../../api/client';
import { useApplyDisplaySettings } from '../../display/DisplayPreferences';
import { DATE_FORMAT_OPTIONS, DEFAULT_DATE_FORMAT, type DateFormat } from '../../lib/dates';
import { DAY_LABELS, DAY_ORDER } from '../../lib/days';
import type { UserSettings } from '../../types/settings';

interface DisplaySectionProps {
  settings: UserSettings;
  onUpdated: (settings: UserSettings) => void;
}

/** §8.1 screen 6 "Display": the first day of the week (Timeline layout and Settings
 * ordering) and the date format (Rev 15: how every date in the UI is written). Both are
 * display-only (§3.7) - neither has any effect on scheduling. A save is pushed to the
 * app-wide display preferences, so other screens pick it up without a reload.
 */
export function DisplaySection({ settings, onUpdated }: DisplaySectionProps): JSX.Element {
  const [firstDayOfWeek, setFirstDayOfWeek] = useState(settings.first_day_of_week);
  const [dateFormat, setDateFormat] = useState<DateFormat>(settings.date_format ?? DEFAULT_DATE_FORMAT);
  const applyDisplaySettings = useApplyDisplaySettings();
  const [bannerError, setBannerError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const handleSave = async (): Promise<void> => {
    setBannerError(null);
    setSuccessMessage(null);
    setSaving(true);
    try {
      const updated = await updateSettings({ first_day_of_week: firstDayOfWeek, date_format: dateFormat });
      onUpdated(updated);
      applyDisplaySettings(updated);
      setSuccessMessage('Display preferences saved.');
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
      <div className="field">
        <label htmlFor="date-format">Date format</label>
        <select id="date-format" value={dateFormat} onChange={(event) => setDateFormat(event.target.value as DateFormat)}>
          {DATE_FORMAT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <button type="button" className="primary" disabled={saving} onClick={() => void handleSave()}>
        {saving ? 'Saving…' : 'Save display preferences'}
      </button>
    </section>
  );
}
