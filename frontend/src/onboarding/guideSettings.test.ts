import { describe, expect, it } from 'vitest';
import {
  DEFAULT_GUIDE_WINDOW,
  guideBudgetToDailyBudget,
  guideHoursToActiveHours,
  readGuideBudget,
  readGuideHours,
} from './guideSettings';

const NINE_TO_FIVE = [{ start: '09:00', end: '17:00' }];

describe('readGuideHours', () => {
  it('reads the same hours on some days as those days and that window', () => {
    const hours = readGuideHours({
      sunday: NINE_TO_FIVE,
      monday: NINE_TO_FIVE,
      tuesday: null,
      wednesday: null,
      thursday: null,
      friday: null,
      saturday: null,
    });
    expect(hours).toEqual({ days: ['monday', 'sunday'], window: NINE_TO_FIVE[0], uniform: true });
  });

  it('flags hours that differ by day', () => {
    const hours = readGuideHours({ monday: NINE_TO_FIVE, tuesday: [{ start: '18:00', end: '22:00' }] });
    expect(hours.uniform).toBe(false);
    expect(hours.window).toEqual(NINE_TO_FIVE[0]);
  });

  it('flags a split day', () => {
    expect(readGuideHours({ monday: [...NINE_TO_FIVE, { start: '18:00', end: '20:00' }] }).uniform).toBe(false);
  });

  it('suggests 09:00-17:00 when no day is open', () => {
    expect(readGuideHours({ monday: null })).toEqual({ days: [], window: DEFAULT_GUIDE_WINDOW, uniform: true });
  });
});

describe('guideHoursToActiveHours', () => {
  it('opens the chosen days and excludes the rest, for all seven days', () => {
    const map = guideHoursToActiveHours(['sunday', 'thursday'], { start: '18:00', end: '22:00' });
    expect(Object.keys(map)).toHaveLength(7);
    expect(map.sunday).toEqual([{ start: '18:00', end: '22:00' }]);
    expect(map.thursday).toEqual([{ start: '18:00', end: '22:00' }]);
    expect(map.monday).toBeNull();
  });
});

describe('daily budget', () => {
  it('reads no budget anywhere as no limit', () => {
    expect(readGuideBudget({ monday: null, tuesday: null })).toEqual({ minutes: null, uniform: true });
  });

  it('reads one budget everywhere as that budget', () => {
    const all = guideBudgetToDailyBudget(120);
    expect(readGuideBudget(all)).toEqual({ minutes: 120, uniform: true });
  });

  it('flags budgets that differ by day', () => {
    const mixed = { ...guideBudgetToDailyBudget(null), monday: 60 };
    expect(readGuideBudget(mixed)).toEqual({ minutes: 60, uniform: false });
  });

  it('writes the same budget on all seven days', () => {
    const map = guideBudgetToDailyBudget(90);
    expect(Object.values(map)).toEqual([90, 90, 90, 90, 90, 90, 90]);
  });
});
