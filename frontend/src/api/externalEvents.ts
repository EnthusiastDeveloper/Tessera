import { apiClient } from './client';
import type { ExternalEvent } from '../types/timeline';

/** `GET /external-events` (design doc §3.11, §7; added Stage 9d). No query params - the
 * cache already self-limits to a 90-day-forward/30-day-past rolling window (§3.12). */
export function listExternalEvents(): Promise<ExternalEvent[]> {
  return apiClient.get<ExternalEvent[]>('/external-events');
}
