import { apiClient } from './client';
import type { Notification } from '../types/notification';

/** `GET /notifications` (design doc §3.4, §8.1 item 5) - undismissed and unresolved
 * only; the filter is applied at the DB layer (`NotificationRepository.list_active`), so
 * a notification that auto-resolved (§3.9) simply stops appearing here on the next call
 * rather than being returned with `resolved_at` populated. There is no single-notification
 * GET, matching this codebase's established no-single-GET-at-POC-scale precedent
 * (`app.task_instances`/`app.task_templates` - see `EditTaskPage`/`TaskDetailPage`). */
export function listNotifications(): Promise<Notification[]> {
  return apiClient.get<Notification[]>('/notifications');
}

/** `POST /notifications/{id}/dismiss` - deliberately unconditional server-side
 * (`app.notifications.service.dismiss`'s own docstring: "Works whether or not it already
 * self-resolved"). Always succeeds and returns the notification's current `resolved_at`
 * untouched by the dismissal itself - a non-null value here means the underlying
 * condition cleared on its own sometime between this panel's list load and this call
 * landing, not because of this dismissal. That is the stale-click race the caller must
 * check the response for (see NotificationsPanel.tsx). */
export function dismissNotification(notificationId: string): Promise<Notification> {
  return apiClient.post<Notification>(`/notifications/${notificationId}/dismiss`);
}
