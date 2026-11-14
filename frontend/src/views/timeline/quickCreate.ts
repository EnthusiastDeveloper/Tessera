import type { CreateTemplatePayload } from '../../api/taskTemplates';
import type { TaskType } from '../../types/task';

/** Quick create from a Timeline selection (design doc 8.1 screen 2, Rev 18). */

const MINUTE = 60_000;
/** The Timeline's drag grid (6.2's 15-minute grid). A selection this short came from a
 * plain click, which means "this half-hour row", so it is widened to 30 minutes. */
export const SNAP_MINUTES = 15;
const CLICK_MINUTES = 30;
/** End of the start date, counted from its start (3.2): "done by the end of that day". */
export const END_OF_DAY_DEADLINE_MINUTES = 24 * 60;

export interface SlotSelection {
  start: Date;
  end: Date;
}

/** What the selection supplies to a new task, in local wall-clock terms. */
export interface SelectedSlot {
  startDate: string; // "YYYY-MM-DD"
  timeOfDay: string; // "HH:MM"
  durationMinutes: number;
}

/** Everything quick create can hand to the full form ("Open full form"). */
export interface QuickTaskPrefill {
  name: string;
  description: string;
  location: string;
  type: TaskType;
  startDate: string;
  fixedTimeOfDay: string;
  estimatedDurationMinutes: number;
  dependencies: string[];
}

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

function nextMidnight(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + 1);
}

/** A selection can start no earlier than now and must end on the day it starts (a
 * midnight end counts as that day). */
export function selectionAllowed(selection: SlotSelection, now: Date = new Date()): boolean {
  return selection.start.getTime() >= now.getTime() && selection.end.getTime() <= nextMidnight(selection.start).getTime();
}

/** The selection as a slot, widening a single click to 30 minutes (not past midnight). */
export function selectedSlot(selection: SlotSelection): SelectedSlot {
  const { start } = selection;
  let end = selection.end;
  if (end.getTime() - start.getTime() <= SNAP_MINUTES * MINUTE) {
    end = new Date(Math.min(start.getTime() + CLICK_MINUTES * MINUTE, nextMidnight(start).getTime()));
  }
  return {
    startDate: `${start.getFullYear()}-${pad(start.getMonth() + 1)}-${pad(start.getDate())}`,
    timeOfDay: `${pad(start.getHours())}:${pad(start.getMinutes())}`,
    durationMinutes: Math.round((end.getTime() - start.getTime()) / MINUTE),
  };
}

export interface QuickFields {
  name: string;
  description: string;
  location: string;
  type: TaskType;
  dependencies: string[];
}

/** A one-time task from the quick form: a fixed one takes the selected time, a flexible
 * one only its date and length and is due by the end of that day (8.1, Rev 18). */
export function quickCreatePayload(slot: SelectedSlot, fields: QuickFields): CreateTemplatePayload {
  return {
    name: fields.name.trim(),
    type: fields.type,
    recurrence: { pattern: 'one_time', anchor: 'calendar' },
    priority: 'medium',
    start_date: slot.startDate,
    estimated_duration_minutes: slot.durationMinutes,
    ...(fields.description.trim() ? { description: fields.description.trim() } : {}),
    ...(fields.location.trim() ? { location: fields.location.trim() } : {}),
    ...(fields.type === 'fixed'
      ? { fixed_time_of_day: slot.timeOfDay }
      : { deadline_offset_minutes: END_OF_DAY_DEADLINE_MINUTES }),
    ...(fields.dependencies.length > 0 ? { dependencies: fields.dependencies } : {}),
  };
}

export function toPrefill(slot: SelectedSlot, fields: QuickFields): QuickTaskPrefill {
  return {
    name: fields.name,
    description: fields.description,
    location: fields.location,
    type: fields.type,
    startDate: slot.startDate,
    fixedTimeOfDay: slot.timeOfDay,
    estimatedDurationMinutes: slot.durationMinutes,
    dependencies: fields.dependencies,
  };
}
