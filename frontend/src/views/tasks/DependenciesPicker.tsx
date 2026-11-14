import { useEffect, useState } from 'react';
import { listInstances } from '../../api/taskInstances';
import type { TaskInstance } from '../../types/task';

interface DependenciesPickerProps {
  selected: string[];
  onChange: (ids: string[]) => void;
  /** The task being edited, which can't depend on itself. */
  excludeId?: string;
  /** Shown under the legend - e.g. that only this occurrence is affected. */
  note?: string;
}

/** The dependency checklist of the task form, at creation and (Rev 17, design doc 6.1)
 * when editing an occurrence. Excludes `completed`/`dismissed` candidates: depending on
 * an already-completed task is a trivial no-op, and `dismissed` never satisfies a
 * dependency (§3.3), so offering either as a choice would just be a footgun. */
export function DependenciesPicker({ selected, onChange, excludeId, note }: DependenciesPickerProps): JSX.Element {
  const [candidates, setCandidates] = useState<TaskInstance[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    listInstances()
      .then((instances) => {
        if (cancelled) return;
        setCandidates(
          instances.filter(
            (instance) => instance.id !== excludeId && instance.status !== 'completed' && instance.status !== 'dismissed'
          )
        );
      })
      .catch(() => {
        if (!cancelled) setCandidates([]);
      });
    return () => {
      cancelled = true;
    };
  }, [excludeId]);

  const toggle = (id: string): void => {
    onChange(selected.includes(id) ? selected.filter((existing) => existing !== id) : [...selected, id]);
  };

  return (
    <fieldset className="field">
      <legend>Dependencies</legend>
      <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)' }}>
        This task can&apos;t start until everything checked below is completed.
        {note ? ` ${note}` : ''}
      </p>
      {candidates === null && <p>Loading tasks…</p>}
      {candidates !== null && candidates.length === 0 && (
        <p style={{ color: 'var(--color-text-muted)' }}>No other tasks to depend on yet.</p>
      )}
      {candidates?.map((instance) => (
        <label key={instance.id} style={{ display: 'block' }}>
          <input type="checkbox" checked={selected.includes(instance.id)} onChange={() => toggle(instance.id)} /> {instance.name}
        </label>
      ))}
    </fieldset>
  );
}
