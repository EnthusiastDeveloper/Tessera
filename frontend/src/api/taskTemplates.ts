import { apiClient } from './client';
import type { ActiveHoursOverride, Priority, Recurrence, TaskInstance, TaskTemplate, TaskType } from '../types/task';
import type { VirtualOccurrence } from '../types/timeline';

export interface CreateTemplatePayload {
  name: string;
  type: TaskType;
  recurrence: Recurrence;
  priority: Priority;
  estimated_duration_minutes: number;
  /** Local "YYYY-MM-DD", required (design doc §3.2, Rev 10). */
  start_date: string;
  description?: string;
  location?: string;
  fixed_time_of_day?: string;
  deadline_offset_minutes?: number;
  reminder_offsets_minutes?: number[];
  active_hours_override?: ActiveHoursOverride | null;
  dependencies?: string[];
}

export interface CreateTemplateResult {
  template: TaskTemplate;
  instance: TaskInstance;
}

/** Genuinely partial (architecture-plan §5.1) - only include the fields actually
 * changed. All fields optional on the wire; `undefined` means "don't touch this field",
 * matching the backend's `model_fields_set` handling. */
export type PatchTemplatePayload = Partial<Omit<CreateTemplatePayload, 'dependencies' | 'type' | 'start_date'>>;

export function createTemplate(payload: CreateTemplatePayload): Promise<CreateTemplateResult> {
  return apiClient.post<CreateTemplateResult>('/task-templates', payload);
}

export function getTemplate(templateId: string): Promise<TaskTemplate> {
  return apiClient.get<TaskTemplate>(`/task-templates/${templateId}`);
}

export interface ThisAndFutureOptions {
  /** The occurrence being edited - the edit reaches it and every open one dated after it
   * (design doc §3.10, Rev 10). Required by the backend for a recurring task. */
  fromInstanceId?: string;
  /** The dialog's "include these" checkbox: also update later occurrences that were
   * edited on their own. */
  includeDetached?: boolean;
}

/** `scope` has exactly one valid value today (`this_and_future`) - a one-time template
 * has no other occurrences to distinguish from, so this is also the path a one-time
 * task's edit form uses (design doc §3.10). */
export function patchTemplateThisAndFuture(
  templateId: string,
  patch: PatchTemplatePayload,
  options: ThisAndFutureOptions = {}
): Promise<TaskTemplate> {
  const query = new URLSearchParams({ scope: 'this_and_future' });
  if (options.fromInstanceId) query.set('from_instance', options.fromInstanceId);
  if (options.includeDetached) query.set('include_detached', 'true');
  return apiClient.patch<TaskTemplate>(`/task-templates/${templateId}?${query.toString()}`, patch);
}

/** `GET /task-templates/projections` (design doc §9.2; added Stage 9d) - Timeline "ghost"
 * occurrences for every recurring template, out to the backend's fixed 30-day horizon.
 * Registered ahead of `/{template_id}` on the backend specifically so this path is never
 * captured as a `template_id` - nothing to replicate client-side, just the matching route. */
export function listProjections(): Promise<VirtualOccurrence[]> {
  return apiClient.get<VirtualOccurrence[]>('/task-templates/projections');
}
