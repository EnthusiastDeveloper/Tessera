import { describe, expect, it } from 'vitest';
import { timezonesDiffer } from './timezone';

describe('timezonesDiffer', () => {
  const now = new Date('2026-03-01T12:00:00Z');

  it('is false for the same zone and for an alias of it', () => {
    expect(timezonesDiffer('America/New_York', 'America/New_York', now)).toBe(false);
    expect(timezonesDiffer('Asia/Kolkata', 'Asia/Calcutta', now)).toBe(false);
  });

  it('is true for zones with different offsets', () => {
    expect(timezonesDiffer('America/New_York', 'Europe/London', now)).toBe(true);
  });

  it('is true for zones that agree today but not after a daylight-saving change', () => {
    // Both UTC+1 in winter; Lagos never observes DST, Berlin does.
    expect(timezonesDiffer('Africa/Lagos', 'Europe/Berlin', new Date('2026-01-15T12:00:00Z'))).toBe(true);
  });
});
