import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DeleteTaskDialog } from './DeleteTaskDialog';
import * as taskInstancesApi from '../../api/taskInstances';
import type { TaskInstance, TaskTemplate } from '../../types/task';

vi.mock('../../api/taskInstances');
const mocked = vi.mocked(taskInstancesApi);

const TEMPLATE: TaskTemplate = {
  id: 'template-1',
  start_date: '2026-01-01',
  name: 'Water the plants',
  type: 'flexible',
  recurrence: { pattern: 'daily', interval: 1, anchor: 'calendar' },
  priority: 'medium',
  estimated_duration_minutes: 30,
  reminder_offsets_minutes: [],
  archived: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  version: 1,
};

function occurrence(id: string, status: TaskInstance['status']): TaskInstance {
  return {
    id,
    template_id: 'template-1',
    name: 'Water the plants',
    type: 'flexible',
    priority: 'medium',
    estimated_duration_minutes: 30,
    detached: false,
    status,
    status_history: [],
    dependencies: [],
    generated_at: '2026-01-01T00:00:00Z',
    nominal_date: '2026-01-01T00:00:00Z',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    version: 1,
  };
}

describe('DeleteTaskDialog (design doc §3.8, Rev 11)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.listInstances.mockImplementation((params) =>
      Promise.resolve(
        params?.template_id
          ? [occurrence('a', 'completed'), occurrence('b', 'in_progress'), occurrence('c', 'scheduled'), occurrence('d', 'dismissed')]
          : []
      )
    );
  });

  it('names how many open occurrences the whole-series delete removes, including started ones', async () => {
    render(<DeleteTaskDialog template={TEMPLATE} instance={occurrence('c', 'scheduled')} onDeleted={vi.fn()} onCancel={vi.fn()} />);
    await waitFor(() => expect(mocked.listInstances).toHaveBeenCalledWith({ template_id: 'template-1' }));

    await userEvent.click(screen.getByLabelText('The whole series'));

    expect(await screen.findByText(/2 open occurrences will be deleted, including 1 in progress\./)).toBeInTheDocument();
    expect(screen.getByText(/Finished ones are kept/)).toBeInTheDocument();
  });

  it('sends the series scope', async () => {
    mocked.deleteInstance.mockResolvedValue({ deleted_instance_id: 'c', unblocked_instance_ids: [], deleted_instance_ids: ['b', 'c'] });
    const onDeleted = vi.fn();
    render(<DeleteTaskDialog template={TEMPLATE} instance={occurrence('c', 'scheduled')} onDeleted={onDeleted} onCancel={vi.fn()} />);

    await userEvent.click(screen.getByLabelText('The whole series'));
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(mocked.deleteInstance).toHaveBeenCalledWith('c', 'this_and_future'));
    expect(onDeleted).toHaveBeenCalled();
  });
});
