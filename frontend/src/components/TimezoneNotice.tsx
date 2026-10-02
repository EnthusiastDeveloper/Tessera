import { Link } from 'react-router-dom';
import { deviceTimezone, timezonesDiffer } from '../lib/timezone';

interface TimezoneNoticeProps {
  /** `UserSettings.timezone`; nothing is shown until it is known. */
  settingsTimezone: string | null;
  /** Set on the create/edit form, where a time of day is typed in. */
  forTimeEntry?: boolean;
}

/** Design doc §14.1/§8.1 (Rev 11): Tessera never moves anything when the timezone
 * setting and the device disagree - it says so, plainly, where it matters. The Timeline
 * draws times in the device's zone (FullCalendar's default); a time of day typed into a
 * task is read in the setting's zone. */
export function TimezoneNotice({ settingsTimezone, forTimeEntry = false }: TimezoneNoticeProps): JSX.Element | null {
  const device = deviceTimezone();
  if (!settingsTimezone || !timezonesDiffer(settingsTimezone, device)) return null;
  return (
    <div className="banner-warning" role="note">
      <strong>Timezone mismatch:</strong> Tessera schedules in <strong>{settingsTimezone}</strong>, but this device is set to{' '}
      <strong>{device}</strong>.{' '}
      {forTimeEntry
        ? `Times of day you enter here are in ${settingsTimezone}.`
        : 'Times on this Timeline are shown in this device’s time.'}{' '}
      <Link to="/settings">Change the timezone setting</Link> if Tessera should use this device’s timezone.
    </div>
  );
}
