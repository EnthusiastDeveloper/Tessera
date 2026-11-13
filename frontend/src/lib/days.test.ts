import { describe, expect, it } from 'vitest';
import { DAY_ORDER, daysOfWeekFrom } from './days';

describe('daysOfWeekFrom', () => {
  it('starts the week on Sunday', () => {
    expect(daysOfWeekFrom('sunday')).toEqual([
      'sunday',
      'monday',
      'tuesday',
      'wednesday',
      'thursday',
      'friday',
      'saturday',
    ]);
  });

  it('is the fixed order when the week starts on Monday', () => {
    expect(daysOfWeekFrom('monday')).toEqual([...DAY_ORDER]);
  });

  it('wraps around from a mid-week start', () => {
    expect(daysOfWeekFrom('thursday')).toEqual([
      'thursday',
      'friday',
      'saturday',
      'sunday',
      'monday',
      'tuesday',
      'wednesday',
    ]);
  });
});
