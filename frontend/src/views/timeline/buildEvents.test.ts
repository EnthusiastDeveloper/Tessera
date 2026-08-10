import { describe, expect, it } from 'vitest';
import { buildBlackoutEvent, buildCalendarEvents, buildExternalEvent, buildRealEvent, buildVirtualEvent } from './buildEvents';
import type { BlackoutDate } from '../../types/settings';
import type { TaskInstance } from '../../types/task';
import type { ExternalEvent, VirtualOccurrence } from '../../types/timeline';

const BASE_INSTANCE: TaskInstance = {
  id: 'instance-1',
  template_id: 'template-1',
  name: 'Water the plants',
  description: null,
  location: null,
  type: 'flexible',
  priority: 2,
  estimated_duration_minutes: 30,
  detached: false,
  scheduled_time: '2026-03-02T18:00:00Z',
  deadline: null,
  status: 'scheduled',
  status_history: [],
  dependencies: [],
  completed_at: null,
  generated_at: '2026-01-01T00:00:00Z',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  version: 1,
};

const BASE_OCCURRENCE: VirtualOccurrence = {
  template_id: 'template-1',
  name: 'Weekly team sync',
  type: 'fixed',
  priority: 2,
  estimated_duration_minutes: 60,
  occurs_at: '2026-03-09T09:00:00Z',
  anchor: 'calendar',
};

const BASE_EXTERNAL_EVENT: ExternalEvent = {
  id: 'evt-1',
  connection_id: 'conn-1',
  provider_event_id: 'provider-evt-1',
  start: '2026-03-02T18:00:00Z',
  end: '2026-03-02T19:00:00Z',
  title: 'Dentist',
  is_all_day: false,
  is_transparent: false,
  fetched_at: '2026-03-01T00:00:00Z',
};

describe('buildRealEvent', () => {
  it('is interactive (kind: real) and carries the instance id for navigation', () => {
    const event = buildRealEvent(BASE_INSTANCE);
    expect(event).not.toBeNull();
    expect(event?.extendedProps).toEqual({ kind: 'real', instanceId: 'instance-1' });
    expect(event?.classNames).toEqual(['fc-event-real']);
  });

  it('computes end from start + estimated_duration_minutes', () => {
    const event = buildRealEvent(BASE_INSTANCE);
    expect(event?.start).toBe('2026-03-02T18:00:00Z');
    expect(event?.end).toBe('2026-03-02T18:30:00.000Z');
  });

  it('returns null when scheduled_time is missing (defensive)', () => {
    expect(buildRealEvent({ ...BASE_INSTANCE, scheduled_time: null })).toBeNull();
  });
});

describe('buildVirtualEvent', () => {
  it('is non-interactive (kind: virtual, no instanceId) and carries no real id', () => {
    const event = buildVirtualEvent(BASE_OCCURRENCE, 0);
    expect(event.extendedProps).toEqual({ kind: 'virtual' });
    expect(event.id).not.toContain('instance');
  });

  it('is visually distinguished with the virtual class', () => {
    const event = buildVirtualEvent(BASE_OCCURRENCE, 0);
    expect(event.classNames).toContain('fc-event-virtual');
  });

  it('adds a further class for completion-anchored occurrences (lower confidence, §9.2)', () => {
    const calendarEvent = buildVirtualEvent({ ...BASE_OCCURRENCE, anchor: 'calendar' }, 0);
    const completionEvent = buildVirtualEvent({ ...BASE_OCCURRENCE, anchor: 'completion' }, 0);
    expect(calendarEvent.classNames).toContain('fc-event-virtual--calendar');
    expect(calendarEvent.classNames).not.toContain('fc-event-virtual--completion');
    expect(completionEvent.classNames).toContain('fc-event-virtual--completion');
  });

  it('is marked non-editable', () => {
    expect(buildVirtualEvent(BASE_OCCURRENCE, 0).editable).toBe(false);
  });

  it('disambiguates same-template occurrences by index', () => {
    const first = buildVirtualEvent(BASE_OCCURRENCE, 0);
    const second = buildVirtualEvent(BASE_OCCURRENCE, 1);
    expect(first.id).not.toBe(second.id);
  });
});

describe('buildExternalEvent', () => {
  it('is non-interactive (kind: external)', () => {
    const event = buildExternalEvent(BASE_EXTERNAL_EVENT);
    expect(event.extendedProps).toEqual({ kind: 'external' });
    expect(event.editable).toBe(false);
  });

  it('renders a timed event without the all-day class', () => {
    const event = buildExternalEvent(BASE_EXTERNAL_EVENT);
    expect(event.allDay).toBe(false);
    expect(event.classNames).toEqual(['fc-event-external']);
  });

  it('renders an all-day event with the distinct overlay class and allDay flag', () => {
    const event = buildExternalEvent({ ...BASE_EXTERNAL_EVENT, is_all_day: true });
    expect(event.allDay).toBe(true);
    expect(event.classNames).toEqual(['fc-event-external', 'fc-event-external--all-day']);
  });
});

describe('buildBlackoutEvent', () => {
  const blackout: BlackoutDate = { start: '2026-03-10', end: '2026-03-12', label: 'Vacation' };

  it('is a background, non-interactive display', () => {
    const event = buildBlackoutEvent(blackout, 0);
    expect(event.display).toBe('background');
    expect(event.editable).toBe(false);
    expect(event.classNames).toEqual(['fc-event-blackout']);
  });

  it('shifts end to the exclusive day after the inclusive backend range', () => {
    const event = buildBlackoutEvent(blackout, 0);
    expect(event.start).toBe('2026-03-10');
    expect(event.end).toBe('2026-03-13');
  });
});

describe('buildCalendarEvents', () => {
  it('trusts the API-supplied projections without reapplying its own horizon cutoff', () => {
    // The 30-day horizon (§9.2) is entirely server-owned; this asserts the frontend
    // renders exactly what the API returns rather than independently truncating or
    // extending it - including an occurrence a naive client-side "within 30 days of
    // today" filter could easily drop by an off-by-one.
    const farOccurrence: VirtualOccurrence = { ...BASE_OCCURRENCE, occurs_at: '2026-12-25T09:00:00Z' };
    const events = buildCalendarEvents({
      instances: [],
      projections: [BASE_OCCURRENCE, farOccurrence],
      externalEvents: [],
      blackoutDates: [],
    });
    expect(events).toHaveLength(2);
  });

  it('composes all four layers', () => {
    const events = buildCalendarEvents({
      instances: [BASE_INSTANCE],
      projections: [BASE_OCCURRENCE],
      externalEvents: [BASE_EXTERNAL_EVENT],
      blackoutDates: [{ start: '2026-03-10', end: '2026-03-10' }],
    });
    const kinds = events.map((e) => (e.extendedProps as { kind: string }).kind).sort();
    expect(kinds).toEqual(['blackout', 'external', 'real', 'virtual']);
  });

  it('drops real events with no scheduled_time rather than crashing', () => {
    const events = buildCalendarEvents({
      instances: [{ ...BASE_INSTANCE, scheduled_time: null }],
      projections: [],
      externalEvents: [],
      blackoutDates: [],
    });
    expect(events).toHaveLength(0);
  });
});
