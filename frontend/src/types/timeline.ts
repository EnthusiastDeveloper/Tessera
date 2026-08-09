// Mirrors backend/app/scheduling/generation.py's `VirtualOccurrence` dataclass and
// backend/app/db/schemas.py's `ExternalEvent` (architecture-plan §9's traceability rule).

import type { RecurrenceAnchor, TaskType } from './task';

/** A projected, non-persisted "ghost" occurrence of a recurring template - design doc
 * §9.2. Deliberately has no `id`/`status`/`dependencies` - it is never a real
 * `TaskInstance` and must never be treated like one (no click-through to edit).
 */
export interface VirtualOccurrence {
  template_id: string;
  name: string;
  type: TaskType;
  priority: number; // numeric, same convention as TaskInstance.priority
  estimated_duration_minutes: number;
  occurs_at: string;
  anchor: RecurrenceAnchor;
}

/** A cached external calendar event (design doc §3.11). Read-only display data only -
 * POC calendar sync never writes back (§7). */
export interface ExternalEvent {
  id: string;
  connection_id: string;
  provider_event_id: string;
  start: string;
  end: string;
  title: string;
  is_all_day: boolean;
  is_transparent: boolean;
  fetched_at: string;
  deleted_at?: string | null;
}
