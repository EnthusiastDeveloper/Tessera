import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { ScheduleRepairOverlay } from './ScheduleRepairOverlay';
import * as settingsApi from '../api/settings';
import { announcePossibleScheduleRepair } from '../lib/scheduleRepairEvents';
import type { ScheduleRepair } from '../types/settings';

vi.mock('../api/settings');
const mocked = vi.mocked(settingsApi);

function repair(overrides: Partial<ScheduleRepair>): ScheduleRepair {
  return { id: 'r1', status: 'running', done: 0, total: 3, moved: 0, unschedulable: 0, ...overrides };
}

function renderOverlay(): void {
  render(
    <MemoryRouter>
      <ScheduleRepairOverlay />
    </MemoryRouter>
  );
}

describe('ScheduleRepairOverlay (design doc §6.10, Rev 11)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a running counter, then a summary', async () => {
    mocked.getScheduleRepair
      .mockResolvedValueOnce(null) // on load: nothing yet
      .mockResolvedValueOnce(repair({ done: 1 }))
      .mockResolvedValueOnce(repair({ done: 2 }))
      .mockResolvedValue(repair({ status: 'finished', done: 3, moved: 2, unschedulable: 1 }));
    renderOverlay();
    await waitFor(() => expect(mocked.getScheduleRepair).toHaveBeenCalledTimes(1));

    act(() => announcePossibleScheduleRepair());

    expect(await screen.findByText('Fixing the calendar (1/3)…')).toBeInTheDocument();
    expect(await screen.findByText('Fixing the calendar (2/3)…', {}, { timeout: 2000 })).toBeInTheDocument();
    expect(await screen.findByText(/Calendar fixed\./, {}, { timeout: 2000 })).toBeInTheDocument();
    expect(screen.getByText(/2 tasks moved to a new time/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'see Notifications' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'OK' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('summarises a repair that finished before the first poll after a save', async () => {
    mocked.getScheduleRepair
      .mockResolvedValueOnce(repair({ id: 'old', status: 'finished', done: 1, total: 1, moved: 1 }))
      .mockResolvedValue(repair({ id: 'new', status: 'finished', done: 1, total: 1, moved: 1 }));
    renderOverlay();
    await waitFor(() => expect(mocked.getScheduleRepair).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument(); // an old repair isn't news

    act(() => announcePossibleScheduleRepair());

    expect(await screen.findByText(/1 task moved to a new time/)).toBeInTheDocument();
  });

  it('shows nothing when a save started no repair', async () => {
    mocked.getScheduleRepair.mockResolvedValue(null);
    renderOverlay();
    act(() => announcePossibleScheduleRepair());
    await waitFor(() => expect(mocked.getScheduleRepair).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('picks a running repair back up after a reload', async () => {
    mocked.getScheduleRepair.mockResolvedValueOnce(repair({ done: 1 })).mockResolvedValue(repair({ status: 'finished', done: 3, moved: 3 }));
    renderOverlay();
    expect(await screen.findByText('Fixing the calendar (1/3)…')).toBeInTheDocument();
    expect(await screen.findByText(/3 tasks moved/, {}, { timeout: 2000 })).toBeInTheDocument();
  });
});
