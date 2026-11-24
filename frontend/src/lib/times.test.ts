import { describe, expect, it } from 'vitest';
import {
  formatClockTime,
  joinLocalDateTime,
  nearestStep,
  parseTimeInput,
  splitLocalDateTime,
  timesOfDay,
} from './times';

describe('formatClockTime', () => {
  it('writes the API time on the chosen clock', () => {
    expect(formatClockTime('17:30', '24h')).toBe('17:30');
    expect(formatClockTime('17:30', '12h')).toBe('5:30 PM');
    expect(formatClockTime('00:15', '12h')).toBe('12:15 AM');
    expect(formatClockTime('12:00', '12h')).toBe('12:00 PM');
    expect(formatClockTime('', '12h')).toBe('');
  });
});

describe('parseTimeInput', () => {
  it.each([
    ['17:30', '17:30'],
    ['1730', '17:30'],
    ['930', '09:30'],
    ['9:05', '09:05'],
    ['17', '17:00'],
    ['0', '00:00'],
    ['5:30pm', '17:30'],
    ['5:30 PM', '17:30'],
    ['5 pm', '17:00'],
    ['5p', '17:00'],
    ['5.30 p.m.', '17:30'],
    ['12am', '00:00'],
    ['12:45 am', '00:45'],
    ['12pm', '12:00'],
    ['11:59 PM', '23:59'],
    ['  08:00  ', '08:00'],
  ])('reads %j as %s', (typed, expected) => {
    expect(parseTimeInput(typed)).toBe(expected);
  });

  it.each(['', 'noon', '24:00', '17:60', '13pm', '0am', '12345', '5:3', ':30'])('refuses %j', (typed) => {
    expect(parseTimeInput(typed)).toBeNull();
  });
});

describe('the picker list', () => {
  it('lists a day in 15-minute steps', () => {
    const times = timesOfDay();
    expect(times).toHaveLength(96);
    expect(times[0]).toBe('00:00');
    expect(times[95]).toBe('23:45');
  });

  it('starts at the value, or the step before it', () => {
    expect(nearestStep('09:15')).toBe('09:15');
    expect(nearestStep('09:29')).toBe('09:15');
    expect(nearestStep('')).toBeNull();
  });
});

describe('local date and time', () => {
  it('round-trips an instant through its local date and time', () => {
    const iso = new Date(2026, 10, 24, 17, 30).toISOString();
    expect(splitLocalDateTime(iso)).toEqual({ date: '2026-11-24', time: '17:30' });
    expect(joinLocalDateTime('2026-11-24', '17:30')).toBe(iso);
  });

  it('gives nothing until both halves are whole', () => {
    expect(splitLocalDateTime(null)).toEqual({ date: '', time: '' });
    expect(joinLocalDateTime('2026-11-24', '')).toBe('');
    expect(joinLocalDateTime('', '17:30')).toBe('');
  });
});
