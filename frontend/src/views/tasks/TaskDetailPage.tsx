import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { ApiError, toApiError } from '../../api/client';
import { useDisplayPreferences } from '../../display/DisplayPreferences';
import { DateTimeInput } from '../../components/DateTimeInput';
import { formatDateTime, formatWeekdayDayMonthTime } from '../../lib/dates';
import { formatDurationCompact } from '../../lib/duration';
import { useOptimization } from '../../optimization/OptimizationContext';
import {
  completeInstance,
  dismissInstance,
  extendDeadline,
  listInstances,
  rescheduleInstance,
  setInstanceDependencies,
  startInstance,
} from '../../api/taskInstances';
import type { TaskInstance, TaskInstanceStatus } from '../../types/task';

type LoadState = 'loading' | 'error' | 'ready';


const TERMINAL_STATUSES: TaskInstanceStatus[] = ['completed', 'dismissed'];
/** Design doc 6.1 (Rev 17): dependencies can be changed until the task is started or finished. */
const DEPENDENCY_EDITABLE_STATUSES: TaskInstanceStatus[] = ['pending', 'scheduled', 'blocked', 'missed'];

interface DependencyDisplay {
  id: string;
  name: string;
  status?: TaskInstanceStatus;
}

// Design doc §8.1 item 4 / DESIGN.md's task-status color mapping - color is always
// accompanied by the status text itself, never the only signal.
const STATUS_COLOR: Record<TaskInstanceStatus, string> = {
  pending: 'var(--color-text-muted)',
  scheduled: 'var(--color-accent)',
  in_progress: 'var(--color-warning)',
  completed: 'var(--color-success)',
  blocked: 'var(--color-status-blocked)',
  missed: 'var(--color-danger)',
  dismissed: 'var(--color-text-muted)',
};

function formatStatus(status: TaskInstanceStatus): string {
  return status.replace('_', ' ');
}

/** Design doc §8.1 item 4: single `TaskInstance` - status, status history, dependencies
 * (both directions), a `detached` indicator, and the five status-gated actions. No
 * single-instance GET endpoint exists at POC scale (implementation-plan's Stage 8
 * reasoning) - like `EditTaskPage`/`DeleteTaskDialog`, this fetches the full instance
 * list once and finds the match client-side; the same list gives both dependency
 * directions for free (forward via `instance.dependencies`, reverse "blocking" by
 * scanning for instances whose `dependencies` include this one - design doc Example D).
 */
export function TaskDetailPage(): JSX.Element {
  const { instanceId } = useParams<{ instanceId: string }>();
  const { dateFormat, timeFormat } = useDisplayPreferences();
  const navigate = useNavigate();
  // Read-only while "Optimize Schedule" runs (design doc §6.11).
  const { locked } = useOptimization();
  const [state, setState] = useState<LoadState>('loading');
  const [instances, setInstances] = useState<TaskInstance[]>([]);
  const [error, setError] = useState<ApiError | null>(null);
  const [newDependency, setNewDependency] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [rescheduleAt, setRescheduleAt] = useState('');
  const [showRescheduleForm, setShowRescheduleForm] = useState(false);
  const [extendDeadlineAt, setExtendDeadlineAt] = useState('');
  const [showExtendForm, setShowExtendForm] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listInstances()
      .then((loaded) => {
        if (cancelled) return;
        setInstances(loaded);
        setState('ready');
      })
      .catch(() => {
        if (!cancelled) setState('error');
      });
    return () => {
      cancelled = true;
    };
  }, [instanceId]);

  const instance = instances.find((candidate) => candidate.id === instanceId) ?? null;

  if (state === 'loading') return <p>Loading…</p>;
  if (state === 'error' || !instance) return <p>Task not found.</p>;

  const nonTerminal = !TERMINAL_STATUSES.includes(instance.status);
  const canStart = instance.status === 'scheduled';
  const canComplete = nonTerminal;
  const canDismiss = nonTerminal;
  const canReschedule = instance.type === 'fixed';
  const canExtendDeadline = instance.status === 'missed';

  const dependencies: DependencyDisplay[] = instance.dependencies.map(
    (id) => instances.find((candidate) => candidate.id === id) ?? { id, name: id, status: undefined }
  );
  const blocking = instances.filter((candidate) => candidate.dependencies.includes(instance.id));
  const canEditDependencies = DEPENDENCY_EDITABLE_STATUSES.includes(instance.status);
  // Not itself, not already listed, and not finished: a completed task would change
  // nothing and a dismissed one would block this task for good (design doc 6.1).
  const addableDependencies = instances.filter(
    (candidate) =>
      candidate.id !== instance.id &&
      !instance.dependencies.includes(candidate.id) &&
      !TERMINAL_STATUSES.includes(candidate.status)
  );

  const applyUpdate = (updated: TaskInstance): void => {
    setInstances((prev) => prev.map((candidate) => (candidate.id === updated.id ? updated : candidate)));
    setShowRescheduleForm(false);
    setShowExtendForm(false);
  };

  const runAction = async (action: () => Promise<TaskInstance>): Promise<void> => {
    setError(null);
    setSubmitting(true);
    try {
      const updated = await action();
      applyUpdate(updated);
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setSubmitting(false);
    }
  };

  const changeDependencies = (ids: string[]): void => {
    setNewDependency('');
    void runAction(() => setInstanceDependencies(instance.id, ids));
  };

  const busy = submitting || locked;
  const priorityLabel = instance.priority.charAt(0).toUpperCase() + instance.priority.slice(1);

  return (
    <div className="max-w-4xl">
      <header className="mb-6">
        <h2 className="mb-2">{instance.name}</h2>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-3 py-1">
            <span className="size-2 rounded-full" style={{ backgroundColor: STATUS_COLOR[instance.status] }} aria-hidden="true" />
            <strong style={{ color: STATUS_COLOR[instance.status] }}>{formatStatus(instance.status)}</strong>
          </span>
          <span className="rounded-full border border-border bg-surface px-3 py-1 text-text-muted">
            {instance.type === 'fixed' ? 'Fixed' : 'Flexible'}
          </span>
          <span className="rounded-full border border-border bg-surface px-3 py-1 text-text-muted">{priorityLabel} priority</span>
          {instance.detached && (
            <span className="rounded-full border border-dashed border-border-strong px-3 py-1 text-text-muted">
              Detached
            </span>
          )}
        </div>
        {instance.detached && (
          <p className="mt-2 mb-0 text-sm text-text-muted">
            This occurrence was edited on its own, so changes to the whole series no longer reach it.
          </p>
        )}
      </header>

      {error && (
        <div className="banner-error" role="alert">
          {error.message}
        </div>
      )}

      <div className="mb-6 flex flex-wrap gap-2">
        {canComplete && (
          <button type="button" className="primary" disabled={busy} onClick={() => void runAction(() => completeInstance(instance.id))}>
            Mark complete
          </button>
        )}
        {canStart && (
          <button type="button" disabled={busy} onClick={() => void runAction(() => startInstance(instance.id))}>
            Mark in progress
          </button>
        )}
        {canReschedule && !showRescheduleForm && (
          <button type="button" disabled={busy} onClick={() => setShowRescheduleForm(true)}>
            Reschedule
          </button>
        )}
        {canExtendDeadline && !showExtendForm && (
          <button type="button" disabled={busy} onClick={() => setShowExtendForm(true)}>
            Extend deadline
          </button>
        )}
        {canDismiss && (
          <button type="button" disabled={busy} onClick={() => void runAction(() => dismissInstance(instance.id))}>
            Skip this occurrence
          </button>
        )}
        <button type="button" disabled={locked} onClick={() => navigate(`/tasks/${instance.id}/edit`)}>
          Edit task
        </button>
      </div>

      {canReschedule && showRescheduleForm && (
        <section className="mb-6 rounded-lg border border-border bg-surface p-4" aria-label="Reschedule">
          <label htmlFor="reschedule-at">New time</label>
          <DateTimeInput
            id="reschedule-at"
            label="New time"
            value={rescheduleAt || (instance.scheduled_time ?? '')}
            onChange={setRescheduleAt}
          />
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              className="primary"
              disabled={submitting || !rescheduleAt}
              onClick={() => void runAction(() => rescheduleInstance(instance.id, rescheduleAt))}
            >
              Confirm reschedule
            </button>
            <button type="button" onClick={() => setShowRescheduleForm(false)}>
              Cancel
            </button>
          </div>
        </section>
      )}

      {canExtendDeadline && showExtendForm && (
        <section className="mb-6 rounded-lg border border-border bg-surface p-4" aria-label="Extend deadline">
          <label htmlFor="extend-deadline-at">New deadline</label>
          <DateTimeInput
            id="extend-deadline-at"
            label="New deadline"
            value={extendDeadlineAt || (instance.deadline ?? '')}
            onChange={setExtendDeadlineAt}
          />
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              className="primary"
              disabled={submitting || !extendDeadlineAt}
              onClick={() => void runAction(() => extendDeadline(instance.id, extendDeadlineAt))}
            >
              Confirm extension
            </button>
            <button type="button" onClick={() => setShowExtendForm(false)}>
              Cancel
            </button>
          </div>
        </section>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-lg border border-border bg-surface p-4" aria-labelledby="task-when">
          <h3 id="task-when" className="mt-0">When</h3>
          <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-text-muted">{instance.type === 'fixed' ? 'Time' : 'Scheduled'}</dt>
            <dd className="m-0">
              {instance.scheduled_time
                ? formatWeekdayDayMonthTime(instance.scheduled_time, dateFormat, timeFormat)
                : 'Not on the Timeline'}
            </dd>
            <dt className="text-text-muted">Duration</dt>
            <dd className="m-0">{formatDurationCompact(instance.estimated_duration_minutes)}</dd>
            {instance.type === 'flexible' && (
              <>
                <dt className="text-text-muted">Due by</dt>
                <dd className="m-0">{instance.deadline ? formatDateTime(instance.deadline, dateFormat, timeFormat) : 'No deadline'}</dd>
              </>
            )}
            {instance.description && (
              <>
                <dt className="text-text-muted">Description</dt>
                <dd className="m-0">{instance.description}</dd>
              </>
            )}
            {instance.location && (
              <>
                <dt className="text-text-muted">Location</dt>
                <dd className="m-0">{instance.location}</dd>
              </>
            )}
          </dl>
        </section>

        <section className="rounded-lg border border-border bg-surface p-4" aria-labelledby="task-dependencies">
          <h3 id="task-dependencies" className="mt-0">Dependencies</h3>
          {dependencies.length === 0 ? (
            <p className="text-sm text-text-muted">This task has no dependencies.</p>
          ) : (
            <ul className="m-0 mb-3 list-none p-0 text-sm">
              {dependencies.map((dep) => (
                <li key={dep.id} className="flex items-center justify-between gap-2 border-b border-border py-1.5 last:border-b-0">
                  <span>
                    {dep.status ? <Link to={`/tasks/${dep.id}`}>{dep.name}</Link> : dep.name}
                    {dep.status ? ` - ${formatStatus(dep.status)}` : ''}
                  </span>
                  {canEditDependencies && (
                    <button
                      type="button"
                      className="px-2 py-0.5 text-sm"
                      disabled={busy}
                      aria-label={`Remove dependency ${dep.name}`}
                      onClick={() => changeDependencies(instance.dependencies.filter((id) => id !== dep.id))}
                    >
                      Remove
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {canEditDependencies && addableDependencies.length > 0 && (
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <select aria-label="Task to wait for" value={newDependency} onChange={(event) => setNewDependency(event.target.value)}>
                <option value="">Wait for another task…</option>
                {addableDependencies.map((candidate) => (
                  <option key={candidate.id} value={candidate.id}>
                    {candidate.name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                disabled={!newDependency || busy}
                onClick={() => changeDependencies([...instance.dependencies, newDependency])}
              >
                Add dependency
              </button>
            </div>
          )}

          <h4 className="mt-4 mb-1 font-sans text-sm font-semibold text-text-muted">Blocking</h4>
          {blocking.length === 0 ? (
            <p className="m-0 text-sm text-text-muted">No other tasks are waiting on this one.</p>
          ) : (
            <ul className="m-0 list-none p-0 text-sm">
              {blocking.map((dependent) => (
                <li key={dependent.id} className="py-1">
                  <Link to={`/tasks/${dependent.id}`}>{dependent.name}</Link> - {formatStatus(dependent.status)}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-lg border border-border bg-surface p-4 md:col-span-2" aria-labelledby="task-history">
          <h3 id="task-history" className="mt-0">Status history</h3>
          {instance.status_history.length === 0 ? (
            <p className="m-0 text-sm text-text-muted">No status changes recorded yet.</p>
          ) : (
            <ol className="m-0 list-none p-0 text-sm">
              {instance.status_history.map((entry, index) => (
                <li key={`${entry.status}-${entry.at}-${index}`} className="flex items-center gap-2 py-1">
                  <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: STATUS_COLOR[entry.status] }} aria-hidden="true" />
                  <span style={{ color: STATUS_COLOR[entry.status] }}>{formatStatus(entry.status)}</span>
                  <span className="text-text-muted">- {formatDateTime(entry.at, dateFormat, timeFormat)}</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </div>
  );
}
