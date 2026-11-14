import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ApiError, toApiError } from '../../api/client';
import { useDisplayPreferences } from '../../display/DisplayPreferences';
import { formatDateTime } from '../../lib/dates';
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

// Design doc §8.1a: durations/instants are stored in a wire format the user is never
// asked to reason about directly, but §6.6/§6.7's reschedule/extend-deadline inputs are
// absolute instants, not durations - a plain `datetime-local` control is the right tool
// here (TaskForm.tsx's "this occurrence" deadline field uses the identical pair).
function toDatetimeLocal(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromDatetimeLocal(value: string): string {
  return new Date(value).toISOString();
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

  return (
    <div>
      <h2>{instance.name}</h2>

      {error && (
        <div className="banner-error" role="alert">
          {error.message}
        </div>
      )}

      {instance.detached && (
        <p style={{ color: 'var(--color-text-muted)' }}>
          <strong>Detached</strong> - this occurrence was edited individually and no longer receives updates from its
          recurring template.
        </p>
      )}

      <dl>
        {instance.description && (
          <>
            <dt>Description</dt>
            <dd>{instance.description}</dd>
          </>
        )}
        {instance.location && (
          <>
            <dt>Location</dt>
            <dd>{instance.location}</dd>
          </>
        )}
        <dt>Type</dt>
        <dd>{instance.type === 'fixed' ? 'Fixed' : 'Flexible'}</dd>
        <dt>Priority</dt>
        <dd>{instance.priority}</dd>
        <dt>Status</dt>
        <dd>
          <strong style={{ color: STATUS_COLOR[instance.status] }}>{formatStatus(instance.status)}</strong>
        </dd>
      </dl>

      <h3>Status history</h3>
      {instance.status_history.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)' }}>No status changes recorded yet.</p>
      ) : (
        <ul>
          {instance.status_history.map((entry, index) => (
            <li key={`${entry.status}-${entry.at}-${index}`}>
              <span style={{ color: STATUS_COLOR[entry.status] }}>{formatStatus(entry.status)}</span>
              {' - '}
              {formatDateTime(entry.at, dateFormat, timeFormat)}
            </li>
          ))}
        </ul>
      )}

      <h3>Dependencies</h3>
      {dependencies.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)' }}>This task has no dependencies.</p>
      ) : (
        <ul>
          {dependencies.map((dep) => (
            <li key={dep.id}>
              {dep.name}
              {dep.status ? ` - ${formatStatus(dep.status)}` : ''}
              {canEditDependencies && (
                <button
                  type="button"
                  className="ml-3 px-2 py-0.5 text-sm"
                  disabled={submitting || locked}
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
            disabled={!newDependency || submitting || locked}
            onClick={() => changeDependencies([...instance.dependencies, newDependency])}
          >
            Add dependency
          </button>
        </div>
      )}

      <h3>Blocking</h3>
      {blocking.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)' }}>No other tasks are waiting on this one.</p>
      ) : (
        <ul>
          {blocking.map((dependent) => (
            <li key={dependent.id}>
              {dependent.name} - {formatStatus(dependent.status)}
            </li>
          ))}
        </ul>
      )}

      <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap', marginTop: 'var(--space-4)' }}>
        {canStart && (
          <button type="button" disabled={submitting || locked} onClick={() => void runAction(() => startInstance(instance.id))}>
            Mark in progress
          </button>
        )}
        {canComplete && (
          <button
            type="button"
            className="primary"
            disabled={submitting || locked}
            onClick={() => void runAction(() => completeInstance(instance.id))}
          >
            Mark complete
          </button>
        )}
        {canDismiss && (
          <button type="button" disabled={submitting || locked} onClick={() => void runAction(() => dismissInstance(instance.id))}>
            Skip this occurrence
          </button>
        )}
        {canReschedule && !showRescheduleForm && (
          <button type="button" disabled={submitting || locked} onClick={() => setShowRescheduleForm(true)}>
            Reschedule
          </button>
        )}
        {canExtendDeadline && !showExtendForm && (
          <button type="button" disabled={submitting || locked} onClick={() => setShowExtendForm(true)}>
            Extend deadline
          </button>
        )}
        <button type="button" disabled={locked} onClick={() => navigate(`/tasks/${instance.id}/edit`)}>
          Edit task
        </button>
      </div>

      {canReschedule && showRescheduleForm && (
        <div className="field">
          <label htmlFor="reschedule-at">New time</label>
          <input
            id="reschedule-at"
            type="datetime-local"
            value={rescheduleAt}
            onChange={(event) => setRescheduleAt(event.target.value)}
          />
          <div style={{ display: 'flex', gap: 'var(--space-3)', marginTop: 'var(--space-2)' }}>
            <button
              type="button"
              className="primary"
              disabled={submitting || !rescheduleAt}
              onClick={() => void runAction(() => rescheduleInstance(instance.id, fromDatetimeLocal(rescheduleAt)))}
            >
              Confirm reschedule
            </button>
            <button type="button" onClick={() => setShowRescheduleForm(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {canExtendDeadline && showExtendForm && (
        <div className="field">
          <label htmlFor="extend-deadline-at">New deadline</label>
          <input
            id="extend-deadline-at"
            type="datetime-local"
            value={extendDeadlineAt || toDatetimeLocal(instance.deadline)}
            onChange={(event) => setExtendDeadlineAt(event.target.value)}
          />
          <div style={{ display: 'flex', gap: 'var(--space-3)', marginTop: 'var(--space-2)' }}>
            <button
              type="button"
              className="primary"
              disabled={submitting || !extendDeadlineAt}
              onClick={() => void runAction(() => extendDeadline(instance.id, fromDatetimeLocal(extendDeadlineAt)))}
            >
              Confirm extension
            </button>
            <button type="button" onClick={() => setShowExtendForm(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
