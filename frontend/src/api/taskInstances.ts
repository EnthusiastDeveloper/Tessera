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
