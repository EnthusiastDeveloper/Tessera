import { apiClient } from './client';
import type { ActiveHoursOverride, Priority, Recurrence, TaskInstance, TaskTemplate, TaskType } from '../types/task';

export interface CreateTemplatePayload {
  name: string;
  type: TaskType;
  recurrence: Recurrence;
  priority: Priority;
  estimated_duration_minutes: number;
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
export type PatchTemplatePayload = Partial<Omit<CreateTemplatePayload, 'dependencies' | 'type'>>;

export function createTemplate(payload: CreateTemplatePayload): Promise<CreateTemplateResult> {
  return apiClient.post<CreateTemplateResult>('/task-templates', payload);
}

export function getTemplate(templateId: string): Promise<TaskTemplate> {
  return apiClient.get<TaskTemplate>(`/task-templates/${templateId}`);
}

/** `scope` has exactly one valid value today (`this_and_future`) - a one-time template
 * has no other occurrences to distinguish from, so this is also the path a one-time
 * task's edit form uses (design doc §3.10). */
export function patchTemplateThisAndFuture(templateId: string, patch: PatchTemplatePayload): Promise<TaskTemplate> {
  return apiClient.patch<TaskTemplate>(`/task-templates/${templateId}?scope=this_and_future`, patch);
}
