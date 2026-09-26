// Mirrors backend/app/db/schemas.py exactly (architecture-plan §9's traceability rule) -
// field names are the wire contract, not just an internal convention.

export type TaskType = 'fixed' | 'flexible';
export type Priority = 'low' | 'medium' | 'high' | 'critical';
export type RecurrencePattern = 'one_time' | 'daily' | 'weekly' | 'monthly' | 'custom';
export type RecurrenceAnchor = 'calendar' | 'completion';
export type TaskInstanceStatus = 'pending' | 'scheduled' | 'in_progress' | 'completed' | 'blocked' | 'missed' | 'dismissed';
export type DayName = 'monday' | 'tuesday' | 'wednesday' | 'thursday' | 'friday' | 'saturday' | 'sunday';

export interface ActiveHoursWindow {
  start: string; // "HH:MM"
  end: string;
}

export interface Recurrence {
  pattern: RecurrencePattern;
  interval?: number | null;
  day_of_week?: number | null;
  day_of_month?: number | null;
  anchor: RecurrenceAnchor;
}

export type ActiveHoursOverride = Partial<Record<DayName, ActiveHoursWindow | null>>;

export interface TaskTemplate {
  id: string;
  name: string;
  description?: string | null;
  location?: string | null;
  type: TaskType;
  recurrence: Recurrence;
  fixed_time_of_day?: string | null;
  deadline_offset_minutes?: number | null;
  priority: Priority;
  estimated_duration_minutes: number;
  reminder_offsets_minutes: number[];
  active_hours_override?: ActiveHoursOverride | null;
  archived: boolean;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface StatusHistoryEntry {
  status: TaskInstanceStatus;
  at: string;
}

export interface TaskInstance {
  id: string;
  template_id: string;
  name: string;
  description?: string | null;
  location?: string | null;
  type: TaskType;
  priority: number;
  estimated_duration_minutes: number;
  detached: boolean;
  scheduled_time?: string | null;
  deadline?: string | null;
  nominal_date?: string | null;
  status: TaskInstanceStatus;
  status_history: StatusHistoryEntry[];
  dependencies: string[];
  completed_at?: string | null;
  generated_at: string;
  created_at: string;
  updated_at: string;
  version: number;
}

export type EditScope = 'this_occurrence' | 'this_and_future';
