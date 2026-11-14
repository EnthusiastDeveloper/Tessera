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
export function availableTimezones(): string[] {
  if (typeof Intl.supportedValuesOf === 'function') {
    return Intl.supportedValuesOf('timeZone');
  }
  return ['UTC'];
}

/** The device's IANA timezone, as the browser reports it. */
export function deviceTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

function offsetMinutes(timezone: string, at: Date): number | null {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: timezone,
      hourCycle: 'h23',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    }).formatToParts(at);
    const get = (type: string): number => Number(parts.find((part) => part.type === type)?.value);
    const asUtc = Date.UTC(get('year'), get('month') - 1, get('day'), get('hour'), get('minute'));
    return Math.round((asUtc - Math.floor(at.getTime() / 60000) * 60000) / 60000);
  } catch {
    return null;
  }
}

/** Whether two IANA names are different clocks. Aliases of one zone ("Asia/Calcutta" and
 * "Asia/Kolkata") are not a mismatch, so beyond the names this compares the zones'
 * offsets now and half a year from now - which also tells daylight-saving rules apart. */
export function timezonesDiffer(a: string, b: string, now: Date = new Date()): boolean {
  if (a === b) return false;
  const later = new Date(now.getTime() + 182 * 24 * 60 * 60 * 1000);
  return [now, later].some((at) => offsetMinutes(a, at) !== offsetMinutes(b, at));
}
