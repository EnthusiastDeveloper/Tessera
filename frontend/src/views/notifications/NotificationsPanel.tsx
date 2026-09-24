import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, toApiError } from '../../api/client';
import { dismissNotification, listNotifications } from '../../api/notifications';
import type { Notification, NotificationType } from '../../types/notification';

type LoadState = 'loading' | 'error' | 'ready';

const TYPE_LABELS: Record<NotificationType, string> = {
  reminder: 'Reminder',
  creation_conflict: 'Creation conflict',
  sync_conflict: 'Sync conflict',
  unschedulable: 'Unschedulable',
  dependency_at_risk: 'Dependency at risk',
  overdue: 'Overdue',
  budget_exceeded: 'Budget exceeded',
  deadline_missed: 'Deadline missed',
};

/** A row's local outcome, tracked independently of the server response shape - `active`
 * is every row's starting state (guaranteed: `GET /notifications` only ever returns
 * undismissed/unresolved rows, per `NotificationRepository.list_active`'s DB-level
 * filter), `dismissed` is the normal path, `already_resolved` is the stale-click race
 * this stage is named for. */
type RowOutcome = 'active' | 'dismissed' | 'already_resolved';

interface Row {
  notification: Notification;
  outcome: RowOutcome;
  dismissing: boolean;
}

/** Design doc §8.1 screen 5 / §3.9: the Notifications panel - undismissed/unresolved
 * `Notification` rows, with dismiss, and an "already resolved" state for the stale-click
 * race where the underlying condition clears server-side between this panel's list load
 * and the user's dismiss click landing.
 *
 * **Interaction design, decided here (documented per this stage's own "decide the exact
 * interaction" instruction):** there is no single-notification GET (matching the
 * established `TaskDetailPage`/`EditTaskPage` precedent of fetching the full list once
 * rather than adding a detail endpoint), and unlike `TaskInstance` a `Notification`
 * carries no field the list response doesn't already include (§3.4's schema is exactly
 * `type`/`related_instance_id`/`message`/timestamps) - so there is no separate "detail"
 * a click could reveal. "Opening" a notification therefore collapses into the one
 * interaction the panel actually offers: Dismiss. That call is also the only server
 * round-trip available to discover a race that happened after the list loaded, which is
 * exactly the mechanism this stage asks for - the dismiss response's `resolved_at` tells
 * us whether the condition was still live at the moment the click reached the server.
 * A manual "Refresh" button re-runs the list fetch for the case where the user wants an
 * up-to-date view without acting on anything (e.g. after leaving the tab open a while).
 */
export function NotificationsPanel(): JSX.Element {
  const [state, setState] = useState<LoadState>('loading');
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState<ApiError | null>(null);

  // Only the most recent load may apply its response - the same guard as the `cancelled`
  // flag other pages use, generalised because `load` also runs on demand (Refresh), not
  // just from the mount effect. Unmounting bumps the counter so an in-flight response
  // is dropped too.
  const latestRequest = useRef(0);

  const load = useCallback(() => {
    const requestId = ++latestRequest.current;
    setState('loading');
    setError(null);
    listNotifications()
      .then((notifications) => {
        if (requestId !== latestRequest.current) return;
        setRows(notifications.map((notification) => ({ notification, outcome: 'active', dismissing: false })));
        setState('ready');
      })
      .catch((err: unknown) => {
        if (requestId !== latestRequest.current) return;
        setError(toApiError(err));
        setState('error');
      });
  }, []);

  useEffect(() => {
    load();
    return () => {
      latestRequest.current += 1;
    };
  }, [load]);

  const handleDismiss = async (id: string): Promise<void> => {
    setError(null);
    setRows((prev) => prev.map((row) => (row.notification.id === id ? { ...row, dismissing: true } : row)));
    try {
      const updated = await dismissNotification(id);
      // `updated.resolved_at` is untouched by `dismiss` itself (see api/notifications.ts) -
      // non-null here means it was already resolved before this call reached the server.
      const outcome: RowOutcome = updated.resolved_at ? 'already_resolved' : 'dismissed';
      setRows((prev) =>
        prev.map((row) => (row.notification.id === id ? { notification: updated, outcome, dismissing: false } : row))
      );
    } catch (err) {
      setError(toApiError(err));
      setRows((prev) => prev.map((row) => (row.notification.id === id ? { ...row, dismissing: false } : row)));
    }
  };

  if (state === 'loading') return <p>Loading…</p>;

  const visibleRows = rows.filter((row) => row.outcome !== 'dismissed');

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <h2>Notifications</h2>
        <button type="button" onClick={load}>
          Refresh
        </button>
      </div>

      {error && (
        <div className="banner-error" role="alert">
          {error.message}
        </div>
      )}

      {visibleRows.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)' }}>No active notifications.</p>
      ) : (
        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {visibleRows.map((row) => (
            <li
              key={row.notification.id}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                gap: 'var(--space-4)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius)',
                backgroundColor: 'var(--color-surface)',
                padding: 'var(--space-4)',
                marginBottom: 'var(--space-3)',
              }}
            >
              <div>
                <strong>{TYPE_LABELS[row.notification.type]}</strong>
                <p style={{ margin: 'var(--space-1) 0' }}>{row.notification.message}</p>
                <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: 'var(--font-size-xs)' }}>
                  {new Date(row.notification.created_at).toLocaleString()}
                </p>
                <Link to={`/tasks/${row.notification.related_instance_id}`}>View task</Link>
              </div>

              {row.outcome === 'already_resolved' ? (
                <p role="status" style={{ margin: 0, color: 'var(--color-text-muted)', whiteSpace: 'nowrap' }}>
                  Already resolved
                </p>
              ) : (
                <button
                  type="button"
                  disabled={row.dismissing}
                  onClick={() => void handleDismiss(row.notification.id)}
                >
                  Dismiss
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
