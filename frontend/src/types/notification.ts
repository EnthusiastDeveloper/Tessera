// Mirrors backend/app/db/schemas.py's `Notification` exactly (architecture-plan §9's
// traceability rule) - field names are the wire contract, not just an internal
// convention. See design doc §3.4 (schema), §5 (type/trigger/resolution reference table).

export type NotificationType =
  | 'reminder'
  | 'creation_conflict'
  | 'sync_conflict'
  | 'unschedulable'
  | 'dependency_at_risk'
  | 'overdue'
  | 'budget_exceeded'
  | 'deadline_missed';

export interface Notification {
  id: string;
  type: NotificationType;
  related_instance_id: string;
  message: string;
  created_at: string;
  dismissed_at?: string | null;
  resolved_at?: string | null;
}
