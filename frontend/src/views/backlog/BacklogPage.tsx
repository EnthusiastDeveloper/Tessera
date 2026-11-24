import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { ApiError, toApiError } from '../../api/client';
import { listNotifications } from '../../api/notifications';
import { completeInstance, dismissInstance, listInstances } from '../../api/taskInstances';
import { useDisplayPreferences } from '../../display/DisplayPreferences';
import { formatDateTime } from '../../lib/dates';
import { formatDurationCompact } from '../../lib/duration';
import { OptimizeControls } from '../../optimization/OptimizeControls';
import { useOptimization } from '../../optimization/OptimizationContext';
import type { TaskInstance, TaskInstanceStatus } from '../../types/task';
import { buildBacklogGroups, type BacklogGroup, type BacklogGroupKey, type BacklogItem, type DependencyLink } from './backlog';

type LoadState = 'loading' | 'error' | 'ready';

const GROUP_TEXT: Record<BacklogGroupKey, { title: string; note: string }> = {
  missed: {
    title: 'Missed deadline',
    note: 'The deadline passed before these were done. Extend the deadline to have one scheduled again, or mark it done or skip it.',
  },
  unschedulable: {
    title: "Couldn't be scheduled",
    note: 'There is no free time for these before their deadline. Give one more time, shorten it, or free up a day.',
  },
  blocked: {
    title: 'Waiting on other tasks',
    note: 'These start once everything they wait on is done. A flexible one is placed on the Timeline then; a fixed one keeps its time.',
  },
};

// Same mapping as the task page: colour always comes with the status text.
const STATUS_CLASS: Record<TaskInstanceStatus, string> = {
  pending: 'text-text-muted',
  scheduled: 'text-accent',
  in_progress: 'text-warning',
  completed: 'text-success',
  blocked: 'text-status-blocked',
  missed: 'text-danger',
  dismissed: 'text-text-muted',
};

function formatStatus(status: TaskInstanceStatus): string {
  return status.replace('_', ' ');
}

function DependencyList({ label, links }: { label: string; links: DependencyLink[] }): JSX.Element | null {
  if (links.length === 0) return null;
  return (
    <p className="m-0 mt-1 text-sm">
      <span className="text-text-muted">{label}: </span>
      {links.map((link, index) => (
        <span key={link.id}>
          {index > 0 && ', '}
          {link.status ? <Link to={`/tasks/${link.id}`}>{link.name}</Link> : link.name}
          {link.status && <span className={STATUS_CLASS[link.status]}> ({formatStatus(link.status)})</span>}
        </span>
      ))}
    </p>
  );
}

/** Design doc 8.1 screen 5a: everything that needs attention and has no place on the
 * Timeline - `blocked`, `pending` with an active `unschedulable` notification, and `missed`.
 * A filter over `TaskInstance` (`GET /task-instances?view=backlog`), not its own entity.
 * Each item shows its dependencies in both directions, linked to the tasks themselves, and
 * the task page is where they are edited (6.1, Rev 17). The Optimize Schedule action sits
 * in the toolbar here too (8.1 screen 2). */
export function BacklogPage(): JSX.Element {
  const { dateFormat, timeFormat } = useDisplayPreferences();
  // Read-only while an optimization runs (6.11); reload when one changed the schedule.
  const { locked, scheduleRevision } = useOptimization();
  const [state, setState] = useState<LoadState>('loading');
  const [groups, setGroups] = useState<BacklogGroup[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listInstances({ view: 'backlog' }), listInstances(), listNotifications()])
      .then(([backlog, all, notifications]) => {
        if (cancelled) return;
        setGroups(buildBacklogGroups(backlog, all, notifications));
        setState('ready');
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(toApiError(err, new ApiError(500, 'unknown_error', 'Failed to load the Backlog.')));
        setState('error');
      });
    return () => {
      cancelled = true;
    };
  }, [scheduleRevision, reloadKey]);

  // Finishing one task can free others waiting on it, so reload rather than drop one row.
  const runAction = async (instanceId: string, action: () => Promise<TaskInstance>): Promise<void> => {
    setError(null);
    setBusyId(instanceId);
    try {
      await action();
      setReloadKey((key) => key + 1);
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setBusyId(null);
    }
  };

  const describe = (instance: TaskInstance): string => {
    const parts = [
      instance.type === 'fixed' ? 'Fixed' : 'Flexible',
      `${instance.priority} priority`,
      formatDurationCompact(instance.estimated_duration_minutes),
    ];
    if (instance.type === 'fixed' && instance.scheduled_time) {
      parts.push(`at ${formatDateTime(instance.scheduled_time, dateFormat, timeFormat)}`);
    } else if (instance.deadline) {
      parts.push(`${instance.status === 'missed' ? 'was due' : 'due'} ${formatDateTime(instance.deadline, dateFormat, timeFormat)}`);
    }
    return parts.join(' · ');
  };

  const renderItem = (item: BacklogItem, key: BacklogGroupKey): JSX.Element => {
    const { instance } = item;
    const busy = busyId === instance.id;
    return (
      <li key={instance.id} className="mb-3 rounded-md border border-border bg-surface px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <Link to={`/tasks/${instance.id}`} className="font-semibold">
              {instance.name}
            </Link>
            <p className="m-0 mt-1 text-sm text-text-muted">{describe(instance)}</p>
            {item.reason && <p className="m-0 mt-1 text-sm">{item.reason}</p>}
            <DependencyList label="Depends on" links={item.waitingOn} />
            <DependencyList label="Needed by" links={item.waitedOnBy} />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {key === 'missed' && (
              <Link to={`/tasks/${instance.id}`} className="text-sm">
                Extend deadline
              </Link>
            )}
            {key === 'blocked' && (
              <Link to={`/tasks/${instance.id}`} className="text-sm">
                Change dependencies
              </Link>
            )}
            <button
              type="button"
              className="text-sm"
              disabled={busy || locked}
              aria-label={`Mark ${instance.name} complete`}
              onClick={() => void runAction(instance.id, () => completeInstance(instance.id))}
            >
              Mark complete
            </button>
            <button
              type="button"
              className="text-sm"
              disabled={busy || locked}
              aria-label={`Skip ${instance.name}`}
              onClick={() => void runAction(instance.id, () => dismissInstance(instance.id))}
            >
              Skip
            </button>
          </div>
        </div>
      </li>
    );
  };

  return (
    <div>
      <h2>Backlog</h2>
      <OptimizeControls />

      {error && (
        <div className="banner-error" role="alert">
          {error.message}
        </div>
      )}

      {state === 'loading' && <p className="text-text-muted">Loading...</p>}

      {state === 'ready' && groups.length === 0 && (
        // Rev 19: say what would land here, so an empty Backlog reads as working, not broken.
        <div className="teaching-note" role="note" aria-label="Your Backlog is empty">
          <p>
            <strong>Nothing needs your attention.</strong> Every open task has a place on the Timeline.
          </p>
          <p>A task is listed here when it has no place on the Timeline:</p>
          <ul>
            <li>its deadline passed before it was done,</li>
            <li>it couldn't be fitted in before its deadline, or</li>
            <li>it is waiting on another task to be done.</li>
          </ul>
        </div>
      )}

      {state === 'ready' &&
        groups.map((group) => (
          <section key={group.key} aria-labelledby={`backlog-${group.key}`} className="mb-6">
            <h3 id={`backlog-${group.key}`} className="mb-1">
              {GROUP_TEXT[group.key].title} <span className="text-text-muted">({group.items.length})</span>
            </h3>
            <p className="m-0 mb-3 text-sm text-text-muted">{GROUP_TEXT[group.key].note}</p>
            <ul className="m-0 list-none p-0">{group.items.map((item) => renderItem(item, group.key))}</ul>
          </section>
        ))}
    </div>
  );
}
