import type { EventInput } from '@fullcalendar/core';
import type { BlackoutDate } from '../../types/settings';
import type { TaskInstance } from '../../types/task';
import type { ExternalEvent, VirtualOccurrence } from '../../types/timeline';

// Design doc §9.2/§7/§8.1 screen 2: four read-only-except-one layers on the Timeline.
// `kind` on `extendedProps` is the single source of truth `TimelinePage`'s `eventClick`
// handler reads to decide whether a click navigates anywhere - real instances are the
// only interactive layer, everything else (`virtual`, `external`, `blackout`) is
// display-only by construction, not by omitting a handler and hoping nothing wires one
// up later.
export type TimelineEventKind = 'real' | 'virtual' | 'external' | 'blackout';

export interface TimelineExtendedProps {
  kind: TimelineEventKind;
  instanceId?: string;
}

function addMinutes(iso: string, minutes: number): string {
  return new Date(new Date(iso).getTime() + minutes * 60_000).toISOString();
}

function addDays(isoDate: string, days: number): string {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** A real, persisted `TaskInstance` - the only interactive layer. Design doc §8.1 item 4
 * links a click through to `TaskDetailPage` (`/tasks/:instanceId`). */
export function buildRealEvent(instance: TaskInstance): EventInput | null {
  if (!instance.scheduled_time) return null; // defensive - callers already filter status=scheduled
  const extendedProps: TimelineExtendedProps = { kind: 'real', instanceId: instance.id };
  return {
    id: `real-${instance.id}`,
    title: instance.name,
    start: instance.scheduled_time,
    end: addMinutes(instance.scheduled_time, instance.estimated_duration_minutes),
    classNames: ['fc-event-real'],
    extendedProps,
  };
}

/** A projected, non-persisted "ghost" occurrence (design doc §9.2). Carries no `id` of
 * its own on the wire - `index` disambiguates multiple occurrences sharing a
 * `template_id` in the same response, purely for FullCalendar's React key/id, never
 * exposed as if it were a real identifier. Visually distinguished per §9.2 ("dimmed/
 * hatched"), with a further `--completion` class for the anchor §9.2 says should read
 * with less confidence than a calendar-anchored ghost.
 */
export function buildVirtualEvent(occurrence: VirtualOccurrence, index: number): EventInput {
  const extendedProps: TimelineExtendedProps = { kind: 'virtual' };
  return {
    id: `virtual-${occurrence.template_id}-${index}`,
    title: occurrence.name,
    start: occurrence.occurs_at,
    end: addMinutes(occurrence.occurs_at, occurrence.estimated_duration_minutes),
    classNames: ['fc-event-virtual', occurrence.anchor === 'completion' ? 'fc-event-virtual--completion' : 'fc-event-virtual--calendar'],
    editable: false,
    extendedProps,
  };
}

/** A cached external calendar event (design doc §3.11, §7). `is_all_day` ones render as
 * the distinct display-only overlay category §7 describes, not a timed busy-block. Both
 * are read-only (POC sync is read-only, §7) - neither ever navigates on click.
 */
export function buildExternalEvent(event: ExternalEvent): EventInput {
  const extendedProps: TimelineExtendedProps = { kind: 'external' };
  return {
    id: `external-${event.id}`,
    title: event.title,
    start: event.start,
    end: event.end,
    allDay: event.is_all_day,
    classNames: event.is_all_day ? ['fc-event-external', 'fc-event-external--all-day'] : ['fc-event-external'],
    editable: false,
    extendedProps,
  };
}

/** A manual blackout date range (design doc §3.7). Rendered as a full-day background
 * highlight, not a foreground "event" competing for the same visual language as an
 * actual task/busy-block - it is a property of the day itself. `end` is exclusive on the
 * wire (FullCalendar's own convention for all-day ranges), so it never has to be
 * point-in-time reconciled against the backend's inclusive `end` (§3.7's "full-day
 * exclusion range") beyond the one-day shift here.
 */
export function buildBlackoutEvent(blackout: BlackoutDate, index: number): EventInput {
  const extendedProps: TimelineExtendedProps = { kind: 'blackout' };
  return {
    id: `blackout-${index}`,
    title: blackout.label ?? 'Blackout',
    start: blackout.start,
    end: addDays(blackout.end, 1),
    allDay: true,
    display: 'background',
    classNames: ['fc-event-blackout'],
    editable: false,
    extendedProps,
  };
}

export interface BuildCalendarEventsInput {
  instances: TaskInstance[];
  projections: VirtualOccurrence[];
  externalEvents: ExternalEvent[];
  blackoutDates: BlackoutDate[];
}

/** Composes all four Timeline layers (design doc §8.1 screen 2) into one FullCalendar
 * event list. Deliberately does not re-filter or re-truncate anything the API already
 * decided (§9.2's 30-day horizon, §7's transparent/all-day split) - this function trusts
 * its inputs and only maps shape, so there is exactly one place (the backend) that owns
 * those business rules.
 */
export function buildCalendarEvents({ instances, projections, externalEvents, blackoutDates }: BuildCalendarEventsInput): EventInput[] {
  return [
    ...instances.map(buildRealEvent).filter((e): e is EventInput => e !== null),
    ...projections.map(buildVirtualEvent),
    ...externalEvents.map(buildExternalEvent),
    ...blackoutDates.map(buildBlackoutEvent),
  ];
}
