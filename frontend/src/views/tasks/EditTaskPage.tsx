import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getTemplate } from '../../api/taskTemplates';
import { listInstances } from '../../api/taskInstances';
import type { TaskInstance, TaskTemplate } from '../../types/task';
import { DeleteTaskDialog } from './DeleteTaskDialog';
import { TaskForm } from './TaskForm';

type LoadState = 'loading' | 'error' | 'ready';

/** Keyed by instance id, not template id - the realistic entry point is "the user
 * clicked a specific occurrence" (from a future Timeline/Backlog/detail screen, Stage
 * 9c/9d), not "the user picked a template out of a list" (no such list screen exists
 * per design doc §8.1). No single-instance GET endpoint exists at POC scale (Stage 8's
 * own reasoning for not adding one - see implementation-plan's Stage 8 section), so this
 * finds the instance via the same list endpoint the Backlog view and dependency pickers
 * already use. */
export function EditTaskPage(): JSX.Element {
  const { instanceId } = useParams<{ instanceId: string }>();
  const navigate = useNavigate();
  const [state, setState] = useState<LoadState>('loading');
  const [template, setTemplate] = useState<TaskTemplate | null>(null);
  const [instance, setInstance] = useState<TaskInstance | null>(null);
  const [showDelete, setShowDelete] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load(): Promise<void> {
      try {
        const instances = await listInstances();
        const found = instances.find((candidate) => candidate.id === instanceId);
        if (!found) {
          if (!cancelled) setState('error');
          return;
        }
        const loadedTemplate = await getTemplate(found.template_id);
        if (cancelled) return;
        setInstance(found);
        setTemplate(loadedTemplate);
        setState('ready');
      } catch {
        if (!cancelled) setState('error');
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [instanceId]);

  if (state === 'loading') return <p>Loading…</p>;
  if (state === 'error' || !template || !instance) return <p>Task not found.</p>;

  return (
    <div>
      <h2>Edit task</h2>
      {showDelete ? (
        <DeleteTaskDialog
          template={template}
          instance={instance}
          onCancel={() => setShowDelete(false)}
          onDeleted={() => navigate('/')}
        />
      ) : (
        <>
          <TaskForm mode="edit" template={template} instance={instance} onSaved={() => navigate('/')} onCancel={() => navigate('/')} />
          <button type="button" className="danger" onClick={() => setShowDelete(true)}>
            Delete task
          </button>
        </>
      )}
    </div>
  );
}
