import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import * as api from '../api/scheduleOptimizations';
import { OptimizationDialogs } from './OptimizationDialogs';
import { OptimizationProvider } from './OptimizationContext';
import { OptimizeControls } from './OptimizeControls';
import { OptimizingBanner } from './OptimizingBanner';
import { AppShell } from '../views/shell/AppShell';
import type {
  OptimizationOpportunity,
  OptimizationSummary,
  ScheduleOptimization,
} from '../types/optimization';

vi.mock('../api/scheduleOptimizations');
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { username: 'admin' }, logout: vi.fn() }),
}));
vi.mock('../api/settings', () => ({ getScheduleRepair: vi.fn().mockResolvedValue(null) }));

const mocked = vi.mocked(api);

const SUMMARY: OptimizationSummary = {
  counts: {
    newly_scheduled: 1,
    moved: 2,
    lost: 0,
    over_budget: 0,
    unchanged: 3,
    still_unplaced: 0,
  },
  newly_scheduled: [{ instance_id: 'a', name: 'Write report', to: '2026-04-06T22:00:00Z' }],
  moved: [
    {
      instance_id: 'b',
      name: 'Water the plants',
      from: '2026-04-06T22:00:00Z',
      to: '2026-04-07T22:00:00Z',
    },
    {
      instance_id: 'c',
      name: 'Call the bank',
      from: '2026-04-06T22:30:00Z',
      to: '2026-04-06T23:00:00Z',
    },
  ],
  lost: [],
  over_budget: [],
};

const DEGRADING: OptimizationSummary = {
  counts: {
    newly_scheduled: 1,
    moved: 0,
    lost: 1,
    over_budget: 1,
    unchanged: 1,
    still_unplaced: 0,
  },
  newly_scheduled: [{ instance_id: 'c', name: 'Pay rent', to: '2026-04-06T23:00:00Z' }],
  moved: [],
  lost: [
    {
      instance_id: 'a',
      name: 'Laundry',
      from: '2026-04-06T23:00:00Z',
      deadline: '2026-04-07T00:00:00Z',
      reason: 'no_slot_before_deadline',
    },
  ],
  over_budget: [{ instance_id: 'x', name: 'Taxes' }],
};

function optimization(overrides: Partial<ScheduleOptimization>): ScheduleOptimization {
  return {
    id: 'opt-1',
    status: 'running',
    requested_at: new Date().toISOString(),
    finished_at: null,
    valid_until: null,
    undo_until: null,
    reason: null,
    plan_changed: false,
    undo_available: false,
    slow_after_seconds: 10,
    timeout_seconds: 30,
    summary: null,
    ...overrides,
  };
}

const WORTHWHILE: OptimizationOpportunity = {
  gain: 1,
  newly_scheduled: 1,
  lost: 0,
  over_budget: 0,
  moved: 2,
  needs_approval: false,
  worthwhile: true,
};
const NOTHING: OptimizationOpportunity = {
  ...WORTHWHILE,
  gain: 0,
  newly_scheduled: 0,
  moved: 0,
  worthwhile: false,
};

const IN_TEN_MINUTES = (): string => new Date(Date.now() + 10 * 60_000).toISOString();

function renderUI(): ReturnType<typeof render> {
  return render(
    <OptimizationProvider>
      <OptimizingBanner />
      <OptimizeControls />
      <OptimizationDialogs />
    </OptimizationProvider>
  );
}

describe('Optimize Schedule', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocked.getLatestOptimization.mockResolvedValue(null);
    mocked.getOptimizationOpportunity.mockResolvedValue(WORTHWHILE);
  });

  it('starts a run, pauses editing while it runs, then shows the summary with an Undo', async () => {
    // Before: the button invites the press - the gain, and the attention-seeking border.
    mocked.getOptimizationOpportunity
      .mockResolvedValueOnce({ ...WORTHWHILE, gain: 3 })
      .mockResolvedValue(NOTHING);
    mocked.startOptimization.mockResolvedValue(optimization({ status: 'running' }));
    renderUI();

    expect(await screen.findByText('3 more tasks could be scheduled')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Optimize Schedule' })).toHaveClass(
      'optimize-button--attention'
    );
    await userEvent.click(await screen.findByRole('button', { name: 'Optimize Schedule' }));
    expect(await screen.findByText(/Optimizing your schedule/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Optimize Schedule' })).toBeDisabled();

    mocked.getLatestOptimization.mockResolvedValue(
      optimization({
        status: 'applied',
        summary: SUMMARY,
        undo_available: true,
        undo_until: IN_TEN_MINUTES(),
      })
    );
    const dialog = await screen.findByRole(
      'dialog',
      { name: 'Schedule optimized' },
      { timeout: 3000 }
    );
    expect(
      within(dialog).getByText(/1 task newly scheduled, 2 moved, 3 left as they were/)
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/Water the plants/)).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Undo' })).toBeInTheDocument();
    expect(screen.queryByText(/Optimizing your schedule/)).not.toBeInTheDocument();

    // After: it did what it could, so the opportunity is asked again and the button is grayed out.
    expect(await screen.findByText('Nothing to improve right now')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Optimize Schedule' })).toBeDisabled();
  });

  it('undoes an applied run and says the schedule was restored', async () => {
    mocked.getLatestOptimization.mockResolvedValue(
      optimization({
        status: 'applied',
        summary: SUMMARY,
        undo_available: true,
        undo_until: IN_TEN_MINUTES(),
      })
    );
    mocked.undoOptimization.mockResolvedValue(
      optimization({ status: 'undone', undo_available: false })
    );
    renderUI();

    await userEvent.click(
      await screen.findByRole('button', { name: /Undo optimization \(\d+:\d\d\)/ })
    );

    expect(mocked.undoOptimization).toHaveBeenCalledWith('opt-1');
    expect(await screen.findByRole('dialog', { name: 'Schedule restored' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Undo optimization/ })).not.toBeInTheDocument();
  });

  it('offers no Undo once undoing is no longer safe, and grays the button out when there is nothing to improve', async () => {
    mocked.getOptimizationOpportunity.mockResolvedValue(NOTHING);
    mocked.getLatestOptimization.mockResolvedValue(
      optimization({
        status: 'applied',
        summary: SUMMARY,
        undo_available: false,
        undo_until: IN_TEN_MINUTES(),
      })
    );
    renderUI();

    const button = await screen.findByRole('button', { name: 'Optimize Schedule' });
    expect(await screen.findByText('Nothing to improve right now')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Undo/ })).not.toBeInTheDocument();
    // Still there (discoverable) but disabled, without the border, saying why - and a click does nothing.
    expect(button).toBeDisabled();
    expect(button).not.toHaveClass('optimize-button--attention');
    expect(button.parentElement).toHaveAttribute('title', 'Nothing to improve right now');
    await userEvent.click(button);
    expect(mocked.startOptimization).not.toHaveBeenCalled();
  });

  it('asks for approval when a plan would lose something, lists what first, and applies on Apply', async () => {
    mocked.getLatestOptimization.mockResolvedValue(
      optimization({
        status: 'awaiting_approval',
        summary: DEGRADING,
        valid_until: IN_TEN_MINUTES(),
      })
    );
    mocked.approveOptimization.mockResolvedValue(optimization({ status: 'running' }));
    mocked.getOptimizationOpportunity.mockResolvedValue({
      ...WORTHWHILE,
      gain: 1,
      lost: 1,
      needs_approval: true,
    });
    renderUI();

    // The hint already says approval will be asked for (and "task", not "tasks", for one).
    expect(
      await screen.findByText('1 more task could be scheduled - needs your approval')
    ).toBeInTheDocument();
    const dialog = await screen.findByRole('dialog', { name: /approval needed/ });
    const sections = within(dialog)
      .getAllByRole('heading', { level: 4 })
      .map((h) => h.textContent);
    expect(sections).toEqual([
      'Would lose their place',
      "Over their day's time budget",
      'Newly scheduled',
    ]);
    expect(within(dialog).getByText(/Laundry/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Nothing has changed yet/)).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole('button', { name: 'Apply' }));
    expect(mocked.approveOptimization).toHaveBeenCalledWith('opt-1');
    expect(await screen.findByText(/Optimizing your schedule/)).toBeInTheDocument();
  });

  it('cancelling an approval declines it, changes nothing and offers no Undo', async () => {
    mocked.getLatestOptimization.mockResolvedValue(
      optimization({
        status: 'awaiting_approval',
        summary: DEGRADING,
        valid_until: IN_TEN_MINUTES(),
      })
    );
    mocked.declineOptimization.mockResolvedValue(optimization({ status: 'declined' }));
    renderUI();

    await userEvent.click(
      within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel' })
    );

    expect(mocked.declineOptimization).toHaveBeenCalledWith('opt-1');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /Undo/ })).not.toBeInTheDocument();
  });

  it('says so when the plan changed after the user last looked', async () => {
    mocked.getLatestOptimization.mockResolvedValue(
      optimization({
        status: 'awaiting_approval',
        summary: DEGRADING,
        plan_changed: true,
        valid_until: IN_TEN_MINUTES(),
      })
    );
    renderUI();
    expect(await screen.findByText(/this is a new plan/)).toBeInTheDocument();
  });

  it.each([
    ['identical', /already as good as it gets/],
    ['would_place_fewer', /leave more tasks without a slot than today/],
  ])('explains "nothing to do" (%s)', async (reason, text) => {
    mocked.startOptimization.mockResolvedValue(optimization({ status: 'running' }));
    mocked.getLatestOptimization.mockResolvedValue(
      optimization({ status: 'nothing_to_do', reason })
    );
    renderUI();
    await userEvent.click(await screen.findByRole('button', { name: 'Optimize Schedule' }));
    const dialog = await screen.findByRole(
      'dialog',
      { name: 'No better arrangement' },
      { timeout: 3000 }
    );
    expect(within(dialog).getByText(text)).toBeInTheDocument();
  });

  it('reports a failure and that nothing was changed', async () => {
    mocked.startOptimization.mockResolvedValue(optimization({ status: 'running' }));
    mocked.getLatestOptimization.mockResolvedValue(
      optimization({ status: 'failed', reason: 'It took too long to finish.' })
    );
    renderUI();
    await userEvent.click(await screen.findByRole('button', { name: 'Optimize Schedule' }));
    const dialog = await screen.findByRole(
      'dialog',
      { name: 'Could not finish' },
      { timeout: 3000 }
    );
    expect(within(dialog).getByText(/took too long/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Nothing was changed/)).toBeInTheDocument();
  });

  it('says it is taking longer than expected once past the server-configured threshold', async () => {
    mocked.getLatestOptimization.mockResolvedValue(
      optimization({
        status: 'running',
        requested_at: new Date(Date.now() - 15_000).toISOString(),
        slow_after_seconds: 10,
      })
    );
    renderUI();
    expect(await screen.findByText(/taking longer than expected/)).toBeInTheDocument();
  });

  it('does not say it before that threshold', async () => {
    mocked.getLatestOptimization.mockResolvedValue(
      optimization({
        status: 'running',
        requested_at: new Date().toISOString(),
        slow_after_seconds: 10,
      })
    );
    renderUI();
    await screen.findByText(/Optimizing your schedule/);
    expect(screen.queryByText(/taking longer than expected/)).not.toBeInTheDocument();
  });

  it('shows a reload mid-run as locked again', async () => {
    mocked.getLatestOptimization.mockResolvedValueOnce(optimization({ status: 'running' }));
    mocked.getLatestOptimization.mockResolvedValue(
      optimization({ status: 'nothing_to_do', reason: 'identical' })
    );
    renderUI();
    expect(await screen.findByText(/Optimizing your schedule/)).toBeInTheDocument();
    expect(mocked.getOptimizationOpportunity).not.toHaveBeenCalled(); // no point asking while it runs
  });

  it('reopens the summary from "What changed" while Undo is offered, and stays an ordinary button if the opportunity cannot be had', async () => {
    mocked.getOptimizationOpportunity.mockRejectedValue(new Error('offline'));
    mocked.getLatestOptimization.mockResolvedValue(
      optimization({
        status: 'applied',
        summary: SUMMARY,
        undo_available: true,
        undo_until: IN_TEN_MINUTES(),
      })
    );
    renderUI();
    await userEvent.click(await screen.findByRole('button', { name: 'What changed' }));
    expect(await screen.findByRole('dialog', { name: 'Schedule optimized' })).toBeInTheDocument();
    const button = screen.getByRole('button', { name: 'Optimize Schedule' });
    expect(button).toBeEnabled();
    expect(button).not.toHaveClass('optimize-button--attention');
    expect(screen.queryByText(/could be scheduled|Nothing to improve/)).not.toBeInTheDocument();
  });
});

describe('the read-only lock in the app shell', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function renderShell(): ReturnType<typeof render> {
    return render(
      <MemoryRouter>
        <AppShell />
      </MemoryRouter>
    );
  }

  it('turns New task into a control that explains itself while an optimization runs', async () => {
    mocked.getLatestOptimization.mockResolvedValue(optimization({ status: 'running' }));
    renderShell();

    // The lock replaces the link-wrapped button, so look the button up again once it is locked.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'New task' })).toHaveAttribute(
        'aria-disabled',
        'true'
      )
    );
    expect(screen.queryByRole('link', { name: 'New task' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'New task' }));
    const hints = await screen.findAllByText(/Editing is paused until it finishes/);
    expect(hints.length).toBeGreaterThanOrEqual(1);
  });

  it('leaves New task a normal link when nothing is running', async () => {
    mocked.getLatestOptimization.mockResolvedValue(null);
    renderShell();
    expect(await screen.findByRole('link', { name: 'New task' })).toHaveAttribute(
      'href',
      '/tasks/new'
    );
  });
});
