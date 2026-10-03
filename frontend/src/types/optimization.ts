// Mirrors backend/app/api/v1/routes/schedule_optimizations.py's `OptimizationResponse`
// (design doc §6.11, Rev 14; architecture-plan §3).

export type OptimizationStatus =
  | 'running'
  | 'awaiting_approval'
  | 'applied'
  | 'nothing_to_do'
  | 'declined'
  | 'undone'
  | 'expired'
  | 'failed';

export interface OptimizationCounts {
  newly_scheduled: number;
  moved: number;
  lost: number;
  over_budget: number;
  unchanged: number;
  still_unplaced: number;
}

export interface OptimizationSummary {
  counts: OptimizationCounts;
  newly_scheduled: { instance_id: string; name: string; to: string }[];
  moved: { instance_id: string; name: string; from: string; to: string }[];
  lost: { instance_id: string; name: string; from: string; deadline: string | null; reason: string }[];
  over_budget: { instance_id: string; name: string }[];
}

export interface ScheduleOptimization {
  id: string;
  status: OptimizationStatus;
  requested_at: string;
  finished_at: string | null;
  valid_until: string | null;
  undo_until: string | null;
  reason: string | null;
  plan_changed: boolean;
  /** Whether Undo is on offer right now - false the moment it stops being safe. */
  undo_available: boolean;
  /** The server's configured limits (`OPTIMIZATION_*`), never hardcoded here. */
  slow_after_seconds: number;
  timeout_seconds: number;
  summary: OptimizationSummary | null;
}
