import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { TaskDetailPage } from './TaskDetailPage';
import * as taskInstancesApi from '../../api/taskInstances';
import type { TaskInstance } from '../../types/task';

vi.mock('../../api/taskInstances');

const mockedInstances = vi.mocked(taskInstancesApi);

const BASE_INSTANCE: TaskInstance = {
  id: 'instance-1',
  template_id: 'template-1',
  name: 'Water the plants',
  description: null,
  location: null,
  type: 'flexible',
  priority: 'medium',
  estimated_duration_minutes: 30,
  detached: false,
  scheduled_time: null,
  deadline: '2026-01-02T00:00:00Z',
  status: 'pending',
  status_history: [],
  dependencies: [],
  completed_at: null,
  generated_at: '2026-01-01T00:00:00Z',
  nominal_date: '2026-01-01T00:00:00Z',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  version: 1,
};

function renderDetail(instances: TaskInstance[], instanceId = 'instance-1'): void {
  mockedInstances.listInstances.mockResolvedValue(instances);
  render(
    <MemoryRouter initialEntries={[`/tasks/${instanceId}`]}>
      <Routes>
        <Route path="/tasks/:instanceId" element={<TaskDetailPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('TaskDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows "Task not found" when the id has no match', async () => {
    renderDetail([]);
    expect(await screen.findByText('Task not found.')).toBeInTheDocument();
  });

  it('renders name, status, and no mutating actions for a completed instance', async () => {
    renderDetail([{ ...BASE_INSTANCE, status: 'completed' }]);
    expect(await screen.findByRole('heading', { name: 'Water the plants' })).toBeInTheDocument();
    expect(screen.getByText('completed')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Mark complete' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Mark in progress' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Skip this occurrence' })).not.toBeInTheDocument();
  });

  it('shows no mutating actions for a dismissed instance', async () => {
    renderDetail([{ ...BASE_INSTANCE, status: 'dismissed' }]);
    await screen.findByRole('heading', { name: 'Water the plants' });
    expect(screen.queryByRole('button', { name: 'Mark complete' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Skip this occurrence' })).not.toBeInTheDocument();
  });

  it('shows mark-in-progress, mark-complete, and dismiss for a scheduled fixed instance, plus reschedule', async () => {
    renderDetail([{ ...BASE_INSTANCE, status: 'scheduled', type: 'fixed' }]);
    await screen.findByRole('heading', { name: 'Water the plants' });
    expect(screen.getByRole('button', { name: 'Mark in progress' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mark complete' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Skip this occurrence' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reschedule' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Extend deadline' })).not.toBeInTheDocument();
  });

  it('does not show reschedule for a scheduled flexible instance', async () => {
    renderDetail([{ ...BASE_INSTANCE, status: 'scheduled', type: 'flexible' }]);
    await screen.findByRole('heading', { name: 'Water the plants' });
    expect(screen.queryByRole('button', { name: 'Reschedule' })).not.toBeInTheDocument();
  });

  it('shows extend-deadline for a missed instance, and not mark-in-progress', async () => {
    renderDetail([{ ...BASE_INSTANCE, status: 'missed' }]);
    await screen.findByRole('heading', { name: 'Water the plants' });
    expect(screen.getByRole('button', { name: 'Extend deadline' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Mark in progress' })).not.toBeInTheDocument();
    // A missed instance is non-terminal, so complete/dismiss remain available.
    expect(screen.getByRole('button', { name: 'Mark complete' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Skip this occurrence' })).toBeInTheDocument();
  });

  it('shows the detached indicator only when detached is true', async () => {
    renderDetail([{ ...BASE_INSTANCE, detached: true }]);
    expect(await screen.findByText(/Detached/)).toBeInTheDocument();
  });

  it('does not show the detached indicator for a non-detached instance', async () => {
    renderDetail([{ ...BASE_INSTANCE, detached: false }]);
    await screen.findByRole('heading', { name: 'Water the plants' });
    expect(screen.queryByText(/Detached/)).not.toBeInTheDocument();
  });

  it('renders dependencies with their current status', async () => {
    const dependency: TaskInstance = { ...BASE_INSTANCE, id: 'dep-1', name: 'Prepare car', status: 'completed' };
    const dependent: TaskInstance = { ...BASE_INSTANCE, id: 'instance-1', dependencies: ['dep-1'] };
    renderDetail([dependency, dependent]);
    await screen.findByRole('heading', { name: 'Water the plants' });
    expect(screen.getByText(/Prepare car/)).toBeInTheDocument();
    expect(screen.getByText(/Prepare car - completed/)).toBeInTheDocument();
  });

  it('renders reverse "blocking" links', async () => {
    const blocked: TaskInstance = { ...BASE_INSTANCE, id: 'dep-2', name: 'Perform annual inspection', status: 'blocked', dependencies: ['instance-1'] };
    renderDetail([BASE_INSTANCE, blocked]);
    await screen.findByRole('heading', { name: 'Water the plants' });
    expect(screen.getByText(/Perform annual inspection - blocked/)).toBeInTheDocument();
  });

  it('marks complete and updates the button set in place', async () => {
    const scheduled: TaskInstance = { ...BASE_INSTANCE, status: 'scheduled' };
    const completed: TaskInstance = { ...BASE_INSTANCE, status: 'completed', completed_at: '2026-01-03T00:00:00Z' };
    mockedInstances.completeInstance.mockResolvedValue(completed);
    renderDetail([scheduled]);
    const completeButton = await screen.findByRole('button', { name: 'Mark complete' });

    await userEvent.click(completeButton);

    await waitFor(() => expect(mockedInstances.completeInstance).toHaveBeenCalledWith('instance-1'));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Mark complete' })).not.toBeInTheDocument());
  });

  describe('changing dependencies (design doc 6.1, Rev 17)', () => {
    const LIGHTS: TaskInstance = { ...BASE_INSTANCE, id: 'lights', name: 'Change the lights', status: 'scheduled' };
    const BULBS: TaskInstance = { ...BASE_INSTANCE, id: 'bulbs', name: 'Buy bulbs', status: 'pending' };
    const DONE: TaskInstance = { ...BASE_INSTANCE, id: 'done', name: 'Old chore', status: 'completed' };

    it('adds a dependency from the other open tasks', async () => {
      mockedInstances.setInstanceDependencies.mockResolvedValue({ ...LIGHTS, status: 'blocked', dependencies: ['bulbs'] });
      renderDetail([LIGHTS, BULBS, DONE], 'lights');
      await screen.findByRole('heading', { name: 'Change the lights' });

      // Not itself, and not a finished task.
      expect(screen.queryByRole('option', { name: 'Change the lights' })).not.toBeInTheDocument();
      expect(screen.queryByRole('option', { name: 'Old chore' })).not.toBeInTheDocument();
      await userEvent.selectOptions(screen.getByLabelText('Task to wait for'), 'bulbs');
      await userEvent.click(screen.getByRole('button', { name: 'Add dependency' }));

      await waitFor(() => expect(mockedInstances.setInstanceDependencies).toHaveBeenCalledWith('lights', ['bulbs']));
      expect(await screen.findByText('blocked')).toBeInTheDocument();
    });

    it('removes one', async () => {
      const blocked = { ...LIGHTS, status: 'blocked' as const, dependencies: ['bulbs'] };
      mockedInstances.setInstanceDependencies.mockResolvedValue({ ...blocked, status: 'pending', dependencies: [] });
      renderDetail([blocked, BULBS], 'lights');
      await screen.findByRole('heading', { name: 'Change the lights' });

      await userEvent.click(screen.getByRole('button', { name: 'Remove dependency Buy bulbs' }));

      await waitFor(() => expect(mockedInstances.setInstanceDependencies).toHaveBeenCalledWith('lights', []));
    });

    it('offers no changes once the task is in progress', async () => {
      renderDetail([{ ...LIGHTS, status: 'in_progress', dependencies: ['bulbs'] }, BULBS], 'lights');
      await screen.findByRole('heading', { name: 'Change the lights' });
      expect(screen.queryByLabelText('Task to wait for')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /Remove dependency/ })).not.toBeInTheDocument();
    });
  });
});
