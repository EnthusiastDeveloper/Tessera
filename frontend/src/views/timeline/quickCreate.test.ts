import { describe, expect, it } from 'vitest';
import { END_OF_DAY_DEADLINE_MINUTES, quickCreatePayload, selectedSlot, selectionAllowed } from './quickCreate';

// Local times, so these hold in any test-runner timezone.
const at = (day: number, hours: number, minutes = 0): Date => new Date(2026, 10, day, hours, minutes);
const NOW = at(14, 10, 7);

describe('selectionAllowed', () => {
  it('takes time from now on, within one day', () => {
    expect(selectionAllowed({ start: at(14, 14), end: at(14, 15) }, NOW)).toBe(true);
    expect(selectionAllowed({ start: at(14, 23), end: at(15, 0) }, NOW)).toBe(true); // ends at midnight
  });

  it('refuses time that has started already', () => {
    expect(selectionAllowed({ start: at(14, 10), end: at(14, 11) }, NOW)).toBe(false);
  });

  it('refuses a selection that runs into the next day', () => {
    expect(selectionAllowed({ start: at(14, 23), end: at(15, 1) }, NOW)).toBe(false);
  });
});

describe('selectedSlot', () => {
  it('reads date, start and length from a drag', () => {
    expect(selectedSlot({ start: at(20, 14), end: at(20, 15, 45) })).toEqual({
      startDate: '2026-11-20',
      timeOfDay: '14:00',
      durationMinutes: 105,
    });
  });

  it('widens a single click to half an hour', () => {
    expect(selectedSlot({ start: at(20, 9, 30), end: at(20, 9, 45) }).durationMinutes).toBe(30);
  });

  it('never widens past midnight', () => {
    expect(selectedSlot({ start: at(20, 23, 45), end: at(21, 0) }).durationMinutes).toBe(15);
  });
});

describe('quickCreatePayload', () => {
  const slot = { startDate: '2026-11-20', timeOfDay: '14:00', durationMinutes: 60 };
  const fields = { name: ' Dentist ', description: '', location: 'Clinic', type: 'fixed' as const, dependencies: [] };

  it('makes a one-time fixed task at the selected time', () => {
    expect(quickCreatePayload(slot, fields)).toEqual({
      name: 'Dentist',
      type: 'fixed',
      recurrence: { pattern: 'one_time', anchor: 'calendar' },
      priority: 'medium',
      start_date: '2026-11-20',
      estimated_duration_minutes: 60,
      location: 'Clinic',
      fixed_time_of_day: '14:00',
    });
  });

  it('makes a flexible task due by the end of that day, with no time of its own', () => {
    const payload = quickCreatePayload(slot, { ...fields, type: 'flexible', dependencies: ['bulbs'] });
    expect(payload.deadline_offset_minutes).toBe(END_OF_DAY_DEADLINE_MINUTES);
    expect(payload.fixed_time_of_day).toBeUndefined();
    expect(payload.dependencies).toEqual(['bulbs']);
  });
});
