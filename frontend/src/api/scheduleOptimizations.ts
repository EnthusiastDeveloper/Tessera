import { apiClient } from './client';
import type { ScheduleOptimization } from '../types/optimization';

/** `POST /schedule-optimizations` - starts the background run (design doc §6.11). */
export function startOptimization(): Promise<ScheduleOptimization> {
  return apiClient.post<ScheduleOptimization>('/schedule-optimizations');
}

/** The latest optimization or `null`; polled while one runs, read on load. */
export function getLatestOptimization(): Promise<ScheduleOptimization | null> {
  return apiClient.get<ScheduleOptimization | null>('/schedule-optimizations/latest');
}

export function approveOptimization(id: string): Promise<ScheduleOptimization> {
  return apiClient.post<ScheduleOptimization>(`/schedule-optimizations/${id}/approve`);
}

export function declineOptimization(id: string): Promise<ScheduleOptimization> {
  return apiClient.post<ScheduleOptimization>(`/schedule-optimizations/${id}/decline`);
}

export function undoOptimization(id: string): Promise<ScheduleOptimization> {
  return apiClient.post<ScheduleOptimization>(`/schedule-optimizations/${id}/undo`);
}
