import { describe, expect, it } from 'vitest';
import {
  DEADLINE_OFFSET_UNITS,
  ESTIMATED_DURATION_UNITS,
  REMINDER_OFFSET_UNITS,
  durationToMinutes,
  formatDurationCompact,
  minutesToDuration,
} from './duration';

describe('minutesToDuration / durationToMinutes round-trip', () => {
  // §8.1a: "formatting a stored value and re-parsing it must yield the same integer" -
  // the greedy formatter (compact display) and the natural user expression can differ,
  // but the single-unit input control's own format/parse pair must always be exact.
  it.each([0, 1, 15, 30, 59, 60, 90, 120, 4320, 10080, 20160, 100000])(
    '%i minutes round-trips through estimated-duration units',
    (minutes) => {
      const { value, unit } = minutesToDuration(minutes, ESTIMATED_DURATION_UNITS);
      expect(durationToMinutes(value, unit)).toBe(minutes);
    }
  );

  it.each([0, 60, 1440, 4320, 10080, 20160, 25])('%i minutes round-trips through deadline-offset units', (minutes) => {
    const { value, unit } = minutesToDuration(minutes, DEADLINE_OFFSET_UNITS);
    expect(durationToMinutes(value, unit)).toBe(minutes);
  });

  it.each([0, 15, 60, 1440, 4321])('%i minutes round-trips through reminder-offset units', (minutes) => {
    const { value, unit } = minutesToDuration(minutes, REMINDER_OFFSET_UNITS);
    expect(durationToMinutes(value, unit)).toBe(minutes);
  });

  it('prefers the largest unit that divides evenly', () => {
    expect(minutesToDuration(180, ESTIMATED_DURATION_UNITS)).toEqual({ value: 3, unit: 'hours' });
    expect(minutesToDuration(4320, DEADLINE_OFFSET_UNITS)).toEqual({ value: 3, unit: 'days' });
  });

  it('falls back to the smallest allowed unit as a decimal when nothing divides evenly', () => {
    // 90 minutes has no exact "hours" representation once minutes isn't an allowed
    // unit for this field - deadline-offset's smallest unit is hours.
    expect(minutesToDuration(90, DEADLINE_OFFSET_UNITS)).toEqual({ value: 1.5, unit: 'hours' });
  });
});

describe('formatDurationCompact', () => {
  it('matches the design doc examples exactly', () => {
    expect(formatDurationCompact(4320)).toBe('3 days');
    expect(formatDurationCompact(90)).toBe('1h 30m');
  });

  it('spells out a single nonzero component as a word', () => {
    expect(formatDurationCompact(60)).toBe('1 hour');
    expect(formatDurationCompact(120)).toBe('2 hours');
    expect(formatDurationCompact(10080)).toBe('1 week');
  });

  it('abbreviates when multiple components combine', () => {
    expect(formatDurationCompact(10140)).toBe('1w 1h');
    expect(formatDurationCompact(1)).toBe('1 minute');
  });

  it('renders zero explicitly', () => {
    expect(formatDurationCompact(0)).toBe('0 minutes');
  });
});
