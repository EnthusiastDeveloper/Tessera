import { useEffect, useState } from 'react';
import { ScopePrompt } from '../../components/ScopePrompt';
import { ApiError, toApiError } from '../../api/client';
import { deleteInstance } from '../../api/taskInstances';
import type { DeleteInstanceResult } from '../../api/taskInstances';
import { listInstances } from '../../api/taskInstances';
import type { EditScope, TaskInstance, TaskTemplate } from '../../types/task';

interface DeleteTaskDialogProps {
  template: TaskTemplate;
  instance: TaskInstance;
  onDeleted: (result: DeleteInstanceResult) => void;
  onCancel: () => void;
}

/** Design doc §3.8/§8.2: an instance with dependents gets an informational notice, not
 * a hard block (deleting just unlinks the dependency); a recurring template's instance
 * additionally requires the same this-occurrence/this-and-future scope choice as
 * editing. There is no third "archive the template but keep the current instance"
 * button here - `scope: this_and_future` already archives the template as part of
 * deleting the instance (backend/app/task_instances/service.py's `delete_instance`),
 * which is the only template-archival path any §8.1 screen actually calls for. */
export function DeleteTaskDialog({ template, instance, onDeleted, onCancel }: DeleteTaskDialogProps): JSX.Element {
  const isRecurring = template.recurrence.pattern !== 'one_time';
  const [scope, setScope] = useState<EditScope | null>(null);
  const [dependentCount, setDependentCount] = useState<number | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listInstances()
      .then((instances) => {
        if (cancelled) return;
        setDependentCount(instances.filter((candidate) => candidate.dependencies.includes(instance.id)).length);
      })
      .catch(() => {
        if (!cancelled) setDependentCount(0);
      });
    return () => {
      cancelled = true;
    };
  }, [instance.id]);

  const scopeChoicePending = isRecurring && scope === null;

  const handleConfirm = async (): Promise<void> => {
    if (scopeChoicePending) return;
    setError(null);
    setSubmitting(true);
    try {
      const result = await deleteInstance(instance.id, isRecurring ? scope! : undefined);
      onDeleted(result);
    } catch (err) {
      setError(toApiError(err));
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-card" role="alertdialog" aria-label="Delete task">
      <h3>Delete &quot;{template.name}&quot;?</h3>

      {error && (
        <div className="banner-error" role="alert">
          {error.message}
        </div>
      )}

      {dependentCount !== null && dependentCount > 0 && (
        <p>
          {dependentCount} task{dependentCount === 1 ? '' : 's'} depend{dependentCount === 1 ? 's' : ''} on this - the
          dependency link will be removed, those tasks will not be deleted.
        </p>
      )}

      {isRecurring ? (
        <>
          <ScopePrompt value={scope} onChange={setScope} name="delete-scope" />
          {scope === 'this_and_future' && (
            <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)' }}>
              This ends the recurring series - no further occurrences will be generated.
            </p>
          )}
        </>
      ) : (
        <p>This task will be permanently deleted.</p>
      )}

      <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
        <button type="button" className="danger" onClick={() => void handleConfirm()} disabled={submitting || scopeChoicePending}>
          {submitting ? 'Deleting…' : 'Delete'}
        </button>
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
