/**
 * Duration entry helpers - design doc §8.1a. Minutes are the storage/wire format only;
 * the user must never compute them or see a raw minute count.
 */

export type DurationUnit = 'minutes' | 'hours' | 'days' | 'weeks';

const UNIT_MINUTES: Record<DurationUnit, number> = {
  minutes: 1,
  hours: 60,
  days: 1440,
  weeks: 10080,
};

const UNIT_WORDS: Record<DurationUnit, { singular: string; plural: string; abbreviation: string }> = {
  minutes: { singular: 'minute', plural: 'minutes', abbreviation: 'm' },
  hours: { singular: 'hour', plural: 'hours', abbreviation: 'h' },
  days: { singular: 'day', plural: 'days', abbreviation: 'd' },
  weeks: { singular: 'week', plural: 'weeks', abbreviation: 'w' },
};

// Per-field allowed unit sets (§8.1a), largest unit first.
export const ESTIMATED_DURATION_UNITS: readonly DurationUnit[] = ['hours', 'minutes'];
export const DEADLINE_OFFSET_UNITS: readonly DurationUnit[] = ['weeks', 'days', 'hours'];
export const REMINDER_OFFSET_UNITS: readonly DurationUnit[] = ['days', 'hours', 'minutes'];
export const DAILY_BUDGET_UNITS: readonly DurationUnit[] = ['hours', 'minutes'];

export interface DurationValue {
  value: number;
  unit: DurationUnit;
}

/**
 * The single-unit representation the input control edits (§8.1a: "a duration control
 * taking a numeric value plus a unit"). Picks the largest unit from `units` that
 * divides `minutes` exactly, so an existing value shows what a person would actually
 * have typed - never "180 minutes" when "3 hours" means the same thing. Falls back to
 * the smallest allowed unit (as a decimal) rather than a unit that would silently lose
 * precision.
 */
export function minutesToDuration(minutes: number, units: readonly DurationUnit[]): DurationValue {
  for (const unit of units) {
    const unitMinutes = UNIT_MINUTES[unit];
    if (minutes % unitMinutes === 0) {
      return { value: minutes / unitMinutes, unit };
    }
  }
  const smallest = units[units.length - 1];
  return { value: minutes / UNIT_MINUTES[smallest], unit: smallest };
}

/**
 * Inverse of `minutesToDuration` - "converting to minutes on submit" (§8.1a). Rounds to
 * the nearest whole minute: the wire format is always integer minutes, and
 * floating-point division (e.g. a fractional-hour entry) must not leak sub-minute noise
 * into what gets sent.
 */
export function durationToMinutes(value: number, unit: DurationUnit): number {
  return Math.round(value * UNIT_MINUTES[unit]);
}

/**
 * Read-only greedy display (§8.1a: "4320 renders as '3 days', 90 as '1h 30m'") - not
 * the input control's format. A single nonzero component spells out the full word
 * ("3 days"); multiple components abbreviate ("1h 30m"), since spelling every one out
 * ("1 hour 30 minutes") reads worse than it saves.
 */
export function formatDurationCompact(minutes: number): string {
  if (minutes === 0) return '0 minutes';

  const order: DurationUnit[] = ['weeks', 'days', 'hours', 'minutes'];
  let remaining = minutes;
  const parts: { amount: number; unit: DurationUnit }[] = [];
  for (const unit of order) {
    const unitMinutes = UNIT_MINUTES[unit];
    const amount = Math.floor(remaining / unitMinutes);
    if (amount > 0) {
      parts.push({ amount, unit });
      remaining -= amount * unitMinutes;
    }
  }

  if (parts.length === 1) {
    const { amount, unit } = parts[0];
    const word = amount === 1 ? UNIT_WORDS[unit].singular : UNIT_WORDS[unit].plural;
    return `${amount} ${word}`;
  }
  return parts.map(({ amount, unit }) => `${amount}${UNIT_WORDS[unit].abbreviation}`).join(' ');
}
