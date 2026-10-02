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
 * additionally asks whether to delete this occurrence or the whole series. The whole
 * series (`scope: this_and_future`) deletes every open occurrence, started ones
 * included, keeps finished ones and archives the template (Rev 11) - the dialog says
 * how many go before the user confirms. */
export function DeleteTaskDialog({ template, instance, onDeleted, onCancel }: DeleteTaskDialogProps): JSX.Element {
  const isRecurring = template.recurrence.pattern !== 'one_time';
  const [scope, setScope] = useState<EditScope | null>(null);
  const [dependentCount, setDependentCount] = useState<number | null>(null);
  const [openSeries, setOpenSeries] = useState<TaskInstance[] | null>(null);
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

  useEffect(() => {
    if (!isRecurring) return;
    let cancelled = false;
    listInstances({ template_id: template.id })
      .then((occurrences) => {
        if (!cancelled) setOpenSeries(occurrences.filter((o) => o.status !== 'completed' && o.status !== 'dismissed'));
      })
      .catch(() => {
        if (!cancelled) setOpenSeries(null);
      });
    return () => {
      cancelled = true;
    };
  }, [isRecurring, template.id]);

  const inProgressCount = openSeries?.filter((o) => o.status === 'in_progress').length ?? 0;

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
          <ScopePrompt value={scope} onChange={setScope} name="delete-scope" seriesLabel="The whole series" />
          {scope === 'this_and_future' && (
            <p role="note">
              {openSeries === null
                ? 'Every open occurrence of this series will be deleted.'
                : `${openSeries.length} open occurrence${openSeries.length === 1 ? '' : 's'} will be deleted` +
                  (inProgressCount > 0 ? `, including ${inProgressCount} in progress.` : '.')}{' '}
              Finished ones are kept. This ends the recurring series - no further occurrences will be generated.
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
