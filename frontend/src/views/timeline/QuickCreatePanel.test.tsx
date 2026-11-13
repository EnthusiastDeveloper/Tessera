import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QuickCreatePanel } from './QuickCreatePanel';
import * as taskTemplatesApi from '../../api/taskTemplates';
import * as taskInstancesApi from '../../api/taskInstances';
import { ApiError } from '../../api/client';
import { selectedSlot } from './quickCreate';
import type { CreateTemplateResult } from '../../api/taskTemplates';

vi.mock('../../api/taskTemplates');
vi.mock('../../api/taskInstances');

const mockedTemplates = vi.mocked(taskTemplatesApi);
const mockedInstances = vi.mocked(taskInstancesApi);

const SELECTION = { start: new Date(2026, 10, 20, 14, 0), end: new Date(2026, 10, 20, 15, 0) };

function renderPanel(overrides: Partial<Parameters<typeof QuickCreatePanel>[0]> = {}): {
  onClose: ReturnType<typeof vi.fn>;
  onCreated: ReturnType<typeof vi.fn>;
  onOpenFullForm: ReturnType<typeof vi.fn>;
} {
  const handlers = { onClose: vi.fn(), onCreated: vi.fn(), onOpenFullForm: vi.fn() };
  render(<QuickCreatePanel selection={SELECTION} slot={selectedSlot(SELECTION)} point={{ x: 100, y: 200 }} {...handlers} {...overrides} />);
  return handlers;
}

describe('QuickCreatePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedInstances.listInstances.mockResolvedValue([]);
    mockedTemplates.createTemplate.mockResolvedValue({} as CreateTemplateResult);
  });

  it('starts as a fixed task at the selected time', () => {
    renderPanel();
    expect(screen.getByLabelText('Fixed')).toBeChecked();
    expect(screen.getByTestId('quick-create-when')).toHaveTextContent('20/11, 14:00 - 15:00');
    expect(screen.getByLabelText('Name')).toHaveFocus();
  });

  it('creates the fixed task and reports back', async () => {
    const { onCreated } = renderPanel();
    await userEvent.type(screen.getByLabelText('Name'), 'Dentist');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    const payload = mockedTemplates.createTemplate.mock.calls[0][0];
    expect(payload).toMatchObject({ name: 'Dentist', type: 'fixed', start_date: '2026-11-20', fixed_time_of_day: '14:00', estimated_duration_minutes: 60 });
  });

  it('as a flexible task, says Tessera picks the time and makes it due that day', async () => {
    renderPanel();
    await userEvent.click(screen.getByLabelText('Flexible'));
    expect(screen.getByTestId('quick-create-when')).toHaveTextContent('Tessera picks the time, by the end of the day.');
    await userEvent.type(screen.getByLabelText('Name'), 'Write the report');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => expect(mockedTemplates.createTemplate).toHaveBeenCalled());
    const payload = mockedTemplates.createTemplate.mock.calls[0][0];
    expect(payload.type).toBe('flexible');
    expect(payload.deadline_offset_minutes).toBe(1440);
    expect(payload.fixed_time_of_day).toBeUndefined();
  });

  it('asks for a name before saving', async () => {
    renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Give the task a name.');
    expect(mockedTemplates.createTemplate).not.toHaveBeenCalled();
  });

  it("shows the server's reason, such as a clash", async () => {
    mockedTemplates.createTemplate.mockRejectedValue(new ApiError(409, 'creation_conflict', 'This overlaps "Team sync".'));
    const { onCreated } = renderPanel();
    await userEvent.type(screen.getByLabelText('Name'), 'Dentist');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('This overlaps "Team sync".');
    expect(onCreated).not.toHaveBeenCalled();
  });

  it('hands everything to the full form', async () => {
    const { onOpenFullForm } = renderPanel();
    await userEvent.type(screen.getByLabelText('Name'), 'Dentist');
    await userEvent.type(screen.getByLabelText('Location'), 'Clinic');
    await userEvent.click(screen.getByRole('button', { name: 'Open full form' }));
    expect(onOpenFullForm).toHaveBeenCalledWith({
      name: 'Dentist',
      description: '',
      location: 'Clinic',
      type: 'fixed',
      startDate: '2026-11-20',
      fixedTimeOfDay: '14:00',
      estimatedDurationMinutes: 60,
      dependencies: [],
    });
  });

  it('closes on Escape and on Cancel without creating anything', async () => {
    const { onClose } = renderPanel();
    await userEvent.keyboard('{Escape}');
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalledTimes(2);
    expect(mockedTemplates.createTemplate).not.toHaveBeenCalled();
  });
});
