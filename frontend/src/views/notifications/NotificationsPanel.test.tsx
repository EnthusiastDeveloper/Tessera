import { StrictMode } from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { NotificationsPanel } from './NotificationsPanel';
import * as notificationsApi from '../../api/notifications';
import type { Notification } from '../../types/notification';

vi.mock('../../api/notifications');

const mockedNotifications = vi.mocked(notificationsApi);

const BASE_NOTIFICATION: Notification = {
  id: 'notification-1',
  type: 'unschedulable',
  related_instance_id: 'instance-1',
  message: '"Water the plants" has no available slot before its deadline.',
  created_at: '2026-01-01T12:00:00Z',
  dismissed_at: null,
  resolved_at: null,
};

function renderPanel(): void {
  render(
    <MemoryRouter initialEntries={['/notifications']}>
      <Routes>
        <Route path="/notifications" element={<NotificationsPanel />} />
        <Route path="/tasks/:instanceId" element={<div>Task detail screen</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('NotificationsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows an empty state when there are no active notifications', async () => {
    mockedNotifications.listNotifications.mockResolvedValue([]);
    renderPanel();
    expect(await screen.findByText('No active notifications.')).toBeInTheDocument();
  });

  it('renders type, message, created_at, and a link to the related task for each notification', async () => {
    const second: Notification = {
      ...BASE_NOTIFICATION,
      id: 'notification-2',
      type: 'overdue',
      related_instance_id: 'instance-2',
      message: 'This task is overdue.',
      created_at: '2026-01-02T09:30:00Z',
    };
    mockedNotifications.listNotifications.mockResolvedValue([BASE_NOTIFICATION, second]);
    renderPanel();

    expect(await screen.findByText('Unschedulable')).toBeInTheDocument();
    expect(screen.getByText(BASE_NOTIFICATION.message)).toBeInTheDocument();
    expect(screen.getByText(new Date(BASE_NOTIFICATION.created_at).toLocaleString())).toBeInTheDocument();

    expect(screen.getByText('Overdue')).toBeInTheDocument();
    expect(screen.getByText(second.message)).toBeInTheDocument();

    const links = screen.getAllByRole('link', { name: 'View task' });
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute('href', '/tasks/instance-1');
    expect(links[1]).toHaveAttribute('href', '/tasks/instance-2');
  });

  it('dismissing a still-active notification (resolved_at still null) removes it from the visible list', async () => {
    mockedNotifications.listNotifications.mockResolvedValue([BASE_NOTIFICATION]);
    mockedNotifications.dismissNotification.mockResolvedValue({
      ...BASE_NOTIFICATION,
      dismissed_at: '2026-01-01T13:00:00Z',
      resolved_at: null,
    });
    renderPanel();

    const dismissButton = await screen.findByRole('button', { name: 'Dismiss' });
    await userEvent.click(dismissButton);

    await waitFor(() => expect(mockedNotifications.dismissNotification).toHaveBeenCalledWith('notification-1'));
    await waitFor(() => expect(screen.queryByText(BASE_NOTIFICATION.message)).not.toBeInTheDocument());
    expect(screen.getByText('No active notifications.')).toBeInTheDocument();
  });

  it('stale-click race: dismiss response already carries resolved_at, shows "already resolved" instead of a plain dismiss', async () => {
    // The list load shows the notification as active (dismissed_at/resolved_at both
    // null, matching what GET /notifications always returns). Between that load and the
    // click landing, the underlying condition cleared server-side - the mocked dismiss
    // response reflects that by coming back with resolved_at already set, exactly as
    // `app.notifications.service.dismiss` does (it never touches resolved_at itself).
    mockedNotifications.listNotifications.mockResolvedValue([BASE_NOTIFICATION]);
    mockedNotifications.dismissNotification.mockResolvedValue({
      ...BASE_NOTIFICATION,
      dismissed_at: '2026-01-01T13:00:00Z',
      resolved_at: '2026-01-01T12:30:00Z',
    });
    renderPanel();

    const dismissButton = await screen.findByRole('button', { name: 'Dismiss' });
    await userEvent.click(dismissButton);

    await waitFor(() => expect(mockedNotifications.dismissNotification).toHaveBeenCalledWith('notification-1'));
    expect(await screen.findByText('Already resolved')).toBeInTheDocument();
    // The row stays visible (not removed like a plain dismiss) and its Dismiss button is gone.
    expect(screen.getByText(BASE_NOTIFICATION.message)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Dismiss' })).not.toBeInTheDocument();
  });

  it('link navigates to the related task detail view', async () => {
    mockedNotifications.listNotifications.mockResolvedValue([BASE_NOTIFICATION]);
    renderPanel();

    const link = await screen.findByRole('link', { name: 'View task' });
    await userEvent.click(link);

    expect(await screen.findByText('Task detail screen')).toBeInTheDocument();
  });

  it('shows an error banner when the list fetch fails', async () => {
    mockedNotifications.listNotifications.mockRejectedValue(new Error('boom'));
    renderPanel();
    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });

  it('refresh re-fetches the list', async () => {
    mockedNotifications.listNotifications.mockResolvedValue([BASE_NOTIFICATION]);
    renderPanel();
    await screen.findByText('Unschedulable');

    mockedNotifications.listNotifications.mockResolvedValue([]);
    await userEvent.click(screen.getByRole('button', { name: 'Refresh' }));

    expect(await screen.findByText('No active notifications.')).toBeInTheDocument();
    expect(mockedNotifications.listNotifications).toHaveBeenCalledTimes(2);
  });

  it('ignores a stale response that resolves after a newer one', async () => {
    // StrictMode mounts, unmounts and remounts, so the list is fetched twice. Let the
    // first (stale) request resolve last - its data must not overwrite the newer one.
    let resolveStale: (value: Notification[]) => void = () => undefined;
    const stale = new Promise<Notification[]>((resolve) => {
      resolveStale = resolve;
    });
    const fresh: Notification = { ...BASE_NOTIFICATION, id: 'notification-fresh', message: 'Fresh notification.' };
    mockedNotifications.listNotifications.mockReturnValueOnce(stale).mockResolvedValueOnce([fresh]);

    render(
      <StrictMode>
        <MemoryRouter initialEntries={['/notifications']}>
          <Routes>
            <Route path="/notifications" element={<NotificationsPanel />} />
          </Routes>
        </MemoryRouter>
      </StrictMode>
    );
    expect(await screen.findByText('Fresh notification.')).toBeInTheDocument();

    resolveStale([{ ...BASE_NOTIFICATION, message: 'Stale notification.' }]);
    await stale;
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(screen.getByText('Fresh notification.')).toBeInTheDocument();
    expect(screen.queryByText('Stale notification.')).not.toBeInTheDocument();
  });
});
