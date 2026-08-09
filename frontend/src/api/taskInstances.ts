import { apiClient } from './client';
import type { EditScope, TaskInstance, TaskInstanceStatus } from '../types/task';

export interface ListInstancesParams {
  status?: TaskInstanceStatus;
  priority?: number;
  type?: 'fixed' | 'flexible';
  view?: 'backlog';
}

export function listInstances(params: ListInstancesParams = {}): Promise<TaskInstance[]> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) query.set(key, String(value));
  }
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return apiClient.get<TaskInstance[]>(`/task-instances${suffix}`);
}

/** §3.10 "this occurrence" edit - only `name`/`description`/`location`/`priority`/
 * `estimated_duration_minutes`/`deadline` may be touched this way; everything else is
 * template-only and goes through `patchTemplateThisAndFuture`. */
export interface PatchInstancePayload {
  name?: string;
  description?: string;
  location?: string;
  priority?: number;
  estimated_duration_minutes?: number;
  deadline?: string;
}

export function patchInstanceThisOccurrence(instanceId: string, patch: PatchInstancePayload): Promise<TaskInstance> {
  return apiClient.patch<TaskInstance>(`/task-instances/${instanceId}`, patch);
}

export interface DeleteInstanceResult {
  deleted_instance_id: string;
  unblocked_instance_ids: string[];
}

/** `scope` is required for a recurring template's instance, ignored/optional for a
 * one-time one (design doc §3.8) - mirrors the edit-scope prompt. */
export function deleteInstance(instanceId: string, scope?: EditScope): Promise<DeleteInstanceResult> {
  const suffix = scope ? `?scope=${scope}` : '';
  return apiClient.delete<DeleteInstanceResult>(`/task-instances/${instanceId}${suffix}`);
}

/** §3.3/§4: reachable directly from `pending`, `blocked`, or `scheduled` - not only via
 * `in_progress`. */
export function completeInstance(instanceId: string): Promise<TaskInstance> {
  return apiClient.post<TaskInstance>(`/task-instances/${instanceId}/complete`);
}

/** §3.8 "skip this occurrence" - terminal (`dismissed`), reachable from any non-terminal
 * status. Preserves the row rather than destroying it. */
export function dismissInstance(instanceId: string): Promise<TaskInstance> {
  return apiClient.post<TaskInstance>(`/task-instances/${instanceId}/dismiss`);
}

/** §4 state diagram: `scheduled` -> `in_progress`, user-triggered and optional - the
 * only inbound edge in the diagram is from `scheduled`. */
export function startInstance(instanceId: string): Promise<TaskInstance> {
  return apiClient.post<TaskInstance>(`/task-instances/${instanceId}/start`);
}

/** §6.6/§3.10: retiming a `fixed` instance - a "this occurrence" edit of
 * `scheduled_time` specifically, so it gets §6.5's hard-block conflict validation. */
export function rescheduleInstance(instanceId: string, scheduledTime: string): Promise<TaskInstance> {
  return apiClient.post<TaskInstance>(`/task-instances/${instanceId}/reschedule`, { scheduled_time: scheduledTime });
}

/** §6.7 resolution path: `missed` -> `pending`, a "this occurrence" edit of `deadline`. */
export function extendDeadline(instanceId: string, deadline: string): Promise<TaskInstance> {
  return apiClient.post<TaskInstance>(`/task-instances/${instanceId}/extend-deadline`, { deadline });
}
