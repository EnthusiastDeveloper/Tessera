import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TaskForm } from './TaskForm';
import * as taskTemplatesApi from '../../api/taskTemplates';
import * as taskInstancesApi from '../../api/taskInstances';
import { ApiError } from '../../api/client';
import type { TaskInstance, TaskTemplate } from '../../types/task';

vi.mock('../../api/taskTemplates');
vi.mock('../../api/taskInstances');

const mockedTemplates = vi.mocked(taskTemplatesApi);
const mockedInstances = vi.mocked(taskInstancesApi);

const BASE_TEMPLATE: TaskTemplate = {
  id: 'template-1',
  name: 'Water the plants',
  description: null,
  location: null,
  type: 'flexible',
  recurrence: { pattern: 'one_time', anchor: 'calendar' },
  fixed_time_of_day: null,
  deadline_offset_minutes: 1440,
  priority: 'medium',
  estimated_duration_minutes: 30,
  reminder_offsets_minutes: [],
  active_hours_override: null,
  archived: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  version: 1,
};

const BASE_INSTANCE: TaskInstance = {
  id: 'instance-1',
  template_id: 'template-1',
  name: 'Water the plants',
  description: null,
  location: null,
  type: 'flexible',
  priority: 2,
  estimated_duration_minutes: 30,
  detached: false,
  scheduled_time: null,
  deadline: '2026-01-02T00:00:00Z',
  status: 'pending',
  status_history: [],
  dependencies: [],
  completed_at: null,
  generated_at: '2026-01-01T00:00:00Z',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  version: 1,
};

describe('TaskForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedInstances.listInstances.mockResolvedValue([]);
  });

  describe('create mode', () => {
    it('has no scope prompt and submits via createTemplate', async () => {
      mockedTemplates.createTemplate.mockResolvedValue({ template: BASE_TEMPLATE, instance: BASE_INSTANCE });
      const onSaved = vi.fn();
      render(<TaskForm mode="create" onSaved={onSaved} onCancel={vi.fn()} />);

      expect(screen.queryByText('Apply to')).not.toBeInTheDocument();

      await userEvent.type(screen.getByLabelText('Name'), 'Water the plants');
      await userEvent.click(screen.getByRole('button', { name: 'Save' }));

      await waitFor(() => expect(mockedTemplates.createTemplate).toHaveBeenCalled());
      const payload = mockedTemplates.createTemplate.mock.calls[0][0];
      expect(payload.name).toBe('Water the plants');
      expect(payload.type).toBe('flexible');
      expect(payload.recurrence.pattern).toBe('one_time');
      expect(onSaved).toHaveBeenCalledWith({ template: BASE_TEMPLATE, instance: BASE_INSTANCE });
    });

    it('shows the active-hours override and dependencies inputs', async () => {
      render(<TaskForm mode="create" onSaved={vi.fn()} onCancel={vi.fn()} />);
      expect(screen.getByText('Active-hours override')).toBeInTheDocument();
      expect(screen.getByText('Dependencies')).toBeInTheDocument();
      await waitFor(() => expect(mockedInstances.listInstances).toHaveBeenCalled());
    });

    it('surfaces infeasible_duration inline', async () => {
      mockedTemplates.createTemplate.mockRejectedValue(
        new ApiError(422, 'infeasible_duration', "This can't fit any day's active hours.")
      );
      render(<TaskForm mode="create" onSaved={vi.fn()} onCancel={vi.fn()} />);

      await userEvent.type(screen.getByLabelText('Name'), 'Impossible task');
      await userEvent.click(screen.getByRole('button', { name: 'Save' }));

      // Surfaced twice on purpose: the banner (generic error display) and inline under
      // the duration field (design doc §8.1's "surfaces the feasibility validation
      // error on save").
      const matches = await screen.findAllByText(/can't fit any day's active hours/i);
      expect(matches.length).toBe(2);
    });
  });

  describe('edit mode, one_time template', () => {
    it('has no scope prompt and submits via patchTemplateThisAndFuture', async () => {
      mockedTemplates.patchTemplateThisAndFuture.mockResolvedValue(BASE_TEMPLATE);
      const onSaved = vi.fn();
      render(<TaskForm mode="edit" template={BASE_TEMPLATE} instance={BASE_INSTANCE} onSaved={onSaved} onCancel={vi.fn()} />);

      expect(screen.queryByText('Apply to')).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Save' }));

      await waitFor(() => expect(mockedTemplates.patchTemplateThisAndFuture).toHaveBeenCalledWith('template-1', expect.anything()));
      expect(mockedInstances.patchInstanceThisOccurrence).not.toHaveBeenCalled();
    });
  });

  describe('edit mode, recurring template', () => {
    const recurringTemplate: TaskTemplate = {
      ...BASE_TEMPLATE,
      recurrence: { pattern: 'weekly', interval: 1, day_of_week: 0, anchor: 'calendar' },
    };

    it('shows the scope prompt and disables Save until a scope is chosen', () => {
      render(<TaskForm mode="edit" template={recurringTemplate} instance={BASE_INSTANCE} onSaved={vi.fn()} onCancel={vi.fn()} />);
      expect(screen.getByText('Apply to')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    });

    it('hides template-only fields once "this occurrence" is chosen, and patches the instance', async () => {
      mockedInstances.patchInstanceThisOccurrence.mockResolvedValue(BASE_INSTANCE);
      const onSaved = vi.fn();
      render(<TaskForm mode="edit" template={recurringTemplate} instance={BASE_INSTANCE} onSaved={onSaved} onCancel={vi.fn()} />);

      await userEvent.click(screen.getByLabelText('This occurrence only'));
      expect(screen.queryByText('Active-hours override')).not.toBeInTheDocument();
      expect(screen.queryByText('Reminders')).not.toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Save' }));

      await waitFor(() => expect(mockedInstances.patchInstanceThisOccurrence).toHaveBeenCalledWith('instance-1', expect.anything()));
      expect(mockedTemplates.patchTemplateThisAndFuture).not.toHaveBeenCalled();
      const patch = mockedInstances.patchInstanceThisOccurrence.mock.calls[0][1];
      expect(patch).not.toHaveProperty('reminder_offsets_minutes');
      expect(patch).not.toHaveProperty('active_hours_override');
    });

    it('keeps template-only fields once "this and future" is chosen, and patches the template', async () => {
      mockedTemplates.patchTemplateThisAndFuture.mockResolvedValue(recurringTemplate);
      render(<TaskForm mode="edit" template={recurringTemplate} instance={BASE_INSTANCE} onSaved={vi.fn()} onCancel={vi.fn()} />);

      await userEvent.click(screen.getByLabelText('This and future occurrences'));
      expect(screen.getByText('Active-hours override')).toBeInTheDocument();

      await userEvent.click(screen.getByRole('button', { name: 'Save' }));

      await waitFor(() =>
        expect(mockedTemplates.patchTemplateThisAndFuture).toHaveBeenCalledWith('template-1', expect.anything())
      );
      expect(mockedInstances.patchInstanceThisOccurrence).not.toHaveBeenCalled();
    });
  });
});
