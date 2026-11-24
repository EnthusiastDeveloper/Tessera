import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { BacklogPage } from './BacklogPage';
import * as taskInstancesApi from '../../api/taskInstances';
import * as notificationsApi from '../../api/notifications';
import * as optimizationApi from '../../api/scheduleOptimizations';
import type { TaskInstance } from '../../types/task';

vi.mock('../../api/taskInstances');
vi.mock('../../api/notifications');
vi.mock('../../api/scheduleOptimizations');

const instancesApi = vi.mocked(taskInstancesApi);
const notifications = vi.mocked(notificationsApi);
const optimization = vi.mocked(optimizationApi);

function task(overrides: Partial<TaskInstance> & Pick<TaskInstance, 'id' | 'name'>): TaskInstance {
  return {
    template_id: `template-${overrides.id}`,
    description: null,
    location: null,
    type: 'flexible',
    priority: 'medium',
    estimated_duration_minutes: 90,
    detached: false,
    scheduled_time: null,
    deadline: '2026-12-01T12:00:00Z',
    nominal_date: '2026-11-30',
    status: 'pending',
    status_history: [],
    dependencies: [],
    completed_at: null,
    generated_at: '2026-11-01T00:00:00Z',
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    version: 1,
    ...overrides,
  };
}

const PREP = task({ id: 'prep', name: 'Prepare car', status: 'scheduled' });
const INSPECTION = task({ id: 'inspect', name: 'Annual inspection', status: 'blocked', dependencies: ['prep'] });
const REPORT = task({ id: 'report', name: 'Write report', status: 'pending' });
const TAXES = task({ id: 'taxes', name: 'File taxes', status: 'missed', priority: 'high' });

function setup(backlog: TaskInstance[], all: TaskInstance[]): void {
  instancesApi.listInstances.mockImplementation((params) =>
    Promise.resolve(params?.view === 'backlog' ? backlog : all)
  );
  notifications.listNotifications.mockResolvedValue([
    {
      id: 'n1',
      type: 'unschedulable',
      related_instance_id: 'report',
      message: 'No free time before the deadline.',
      created_at: '2026-11-01T00:00:00Z',
    },
  ]);
  optimization.getOptimizationOpportunity.mockRejectedValue(new Error('not needed here'));
  render(
    <MemoryRouter>
      <BacklogPage />
    </MemoryRouter>
  );
}

describe('BacklogPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('lists each kind of backlog work in its own section, with the reason and both dependency directions', async () => {
    setup([INSPECTION, REPORT, TAXES], [PREP, INSPECTION, REPORT, TAXES]);

    const missed = await screen.findByRole('region', { name: /Missed deadline/ });
    expect(within(missed).getByRole('link', { name: 'File taxes' })).toHaveAttribute('href', '/tasks/taxes');
    expect(within(missed).getByRole('link', { name: 'Extend deadline' })).toBeInTheDocument();

    const unschedulable = screen.getByRole('region', { name: /Couldn't be scheduled/ });
    expect(within(unschedulable).getByText('No free time before the deadline.')).toBeInTheDocument();

    const blocked = screen.getByRole('region', { name: /Waiting on other tasks/ });
    expect(within(blocked).getByRole('link', { name: 'Prepare car' })).toHaveAttribute('href', '/tasks/prep');
    expect(within(blocked).getByText('(scheduled)')).toBeInTheDocument();
    expect(within(blocked).getByRole('link', { name: 'Change dependencies' })).toHaveAttribute('href', '/tasks/inspect');

    // The backlog filter and the full list (for dependency names) are both asked for.
    expect(instancesApi.listInstances).toHaveBeenCalledWith({ view: 'backlog' });
  });

  it('shows what waits on a backlog task', async () => {
    const follow = task({ id: 'trip', name: 'Road trip', status: 'blocked', dependencies: ['inspect'] });
    setup([INSPECTION, follow], [PREP, INSPECTION, follow]);
    await screen.findByRole('region', { name: /Waiting on other tasks/ });
    const item = screen.getAllByRole('listitem').find((li) => li.textContent?.startsWith('Annual inspection')) as HTMLElement;
    expect(within(item).getByText(/Needed by/)).toBeInTheDocument();
    expect(within(item).getByRole('link', { name: 'Road trip' })).toBeInTheDocument();
  });

  it('says so when nothing needs attention', async () => {
    setup([], [PREP]);
    expect(await screen.findByText(/Nothing needs your attention/)).toBeInTheDocument();
    // Rev 19: and names the three ways a task lands here.
    const note = screen.getByRole('note', { name: 'Your Backlog is empty' });
    expect(note).toHaveTextContent(/deadline passed/);
    expect(note).toHaveTextContent(/couldn't be fitted in/);
    expect(note).toHaveTextContent(/waiting on another task/);
  });

  it('marks a task complete and reloads, since that can free tasks waiting on it', async () => {
    setup([TAXES], [TAXES]);
    instancesApi.completeInstance.mockResolvedValue({ ...TAXES, status: 'completed' });
    await userEvent.click(await screen.findByRole('button', { name: 'Mark File taxes complete' }));
    expect(instancesApi.completeInstance).toHaveBeenCalledWith('taxes');
    await waitFor(() => expect(instancesApi.listInstances).toHaveBeenCalledTimes(4));
  });

  it('skips a task', async () => {
    setup([TAXES], [TAXES]);
    instancesApi.dismissInstance.mockResolvedValue({ ...TAXES, status: 'dismissed' });
    await userEvent.click(await screen.findByRole('button', { name: 'Skip File taxes' }));
    expect(instancesApi.dismissInstance).toHaveBeenCalledWith('taxes');
  });

  it('shows the error when an action is refused', async () => {
    setup([TAXES], [TAXES]);
    const { ApiError } = await import('../../api/client');
    instancesApi.dismissInstance.mockRejectedValue(new ApiError(409, 'conflict', 'Someone changed this task.'));
    await userEvent.click(await screen.findByRole('button', { name: 'Skip File taxes' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Someone changed this task.');
  });
});
