import { describe, expect, it } from 'vitest';
import { formatDate, formatDateTime, formatDayMonth, formatTime, formatWeekdayDayMonth } from './dates';

// Local time, so the expectations hold in any test-runner timezone.
const NOV_13 = new Date(2026, 10, 13, 8, 5);
const MAR_2 = new Date(2026, 2, 2, 18, 30);

describe('formatDate', () => {
  it('puts the day first by default format', () => {
    expect(formatDate(NOV_13, 'DD/MM/YYYY')).toBe('13/11/2026');
  });

  it('puts the month first when asked', () => {
    expect(formatDate(NOV_13, 'MM/DD/YYYY')).toBe('11/13/2026');
  });

  it('writes ISO year-month-day', () => {
    expect(formatDate(NOV_13, 'YYYY-MM-DD')).toBe('2026-11-13');
  });

  it('pads single-digit days and months', () => {
    expect(formatDate(MAR_2, 'DD/MM/YYYY')).toBe('02/03/2026');
  });

  it('accepts an ISO string', () => {
    expect(formatDate(MAR_2.toISOString(), 'DD/MM/YYYY')).toBe('02/03/2026');
  });
});

describe('formatDayMonth', () => {
  it('drops the year in the same order as the full format', () => {
    expect(formatDayMonth(MAR_2, 'DD/MM/YYYY')).toBe('02/03');
    expect(formatDayMonth(MAR_2, 'MM/DD/YYYY')).toBe('03/02');
    expect(formatDayMonth(MAR_2, 'YYYY-MM-DD')).toBe('03-02');
  });
});

describe('combined formats', () => {
  it('appends the time to the date', () => {
    expect(formatDateTime(NOV_13, 'DD/MM/YYYY')).toBe(`13/11/2026 ${formatTime(NOV_13)}`);
  });

  it('leads a short date with the weekday', () => {
    expect(formatWeekdayDayMonth(NOV_13, 'DD/MM/YYYY')).toMatch(/^\S+ 13\/11$/);
  });
});
