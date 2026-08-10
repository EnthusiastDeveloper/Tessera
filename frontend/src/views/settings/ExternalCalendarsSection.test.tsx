import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ExternalCalendarsSection } from './ExternalCalendarsSection';
import * as calendarConnectionsApi from '../../api/calendarConnections';
import { ApiError } from '../../api/client';
import type { ExternalCalendarConnection } from '../../types/calendarConnection';

vi.mock('../../api/calendarConnections');

const mockedApi = vi.mocked(calendarConnectionsApi);

const CONNECTION: ExternalCalendarConnection = {
  id: 'conn-1',
  provider: 'google',
  oauth_credentials_ref: 'token-1',
  refresh_interval_minutes: 15,
  last_synced_at: '2026-01-01T12:00:00Z',
  sync_mode: 'read_only',
  enabled: true,
};

describe('ExternalCalendarsSection', () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(window, 'location', { writable: true, value: { ...originalLocation, href: '' } });
  });

  afterEach(() => {
    Object.defineProperty(window, 'location', { writable: true, value: originalLocation });
  });

  it('shows an empty state when nothing is connected', async () => {
    mockedApi.listConnections.mockResolvedValue([]);
    render(<ExternalCalendarsSection />);
    expect(await screen.findByText('No calendars connected.')).toBeInTheDocument();
  });

  it('renders provider, last-synced timestamp, and refresh interval for each connection', async () => {
    mockedApi.listConnections.mockResolvedValue([CONNECTION]);
    render(<ExternalCalendarsSection />);

    expect(await screen.findByText('Google Calendar')).toBeInTheDocument();
    expect(screen.getByText(new RegExp(new Date(CONNECTION.last_synced_at as string).toLocaleString()))).toBeInTheDocument();
    expect(screen.getByText(/15 minutes/)).toBeInTheDocument();
  });

  it('shows "Never synced" when a connection has no last_synced_at', async () => {
    mockedApi.listConnections.mockResolvedValue([{ ...CONNECTION, last_synced_at: null }]);
    render(<ExternalCalendarsSection />);
    expect(await screen.findByText(/never synced/i)).toBeInTheDocument();
  });

  it('clicking "Connect Google Calendar" navigates the browser to the returned authorize_url', async () => {
    mockedApi.listConnections.mockResolvedValue([]);
    mockedApi.connect.mockResolvedValue({ authorize_url: 'https://accounts.google.com/o/oauth2/v2/auth?state=abc' });
    render(<ExternalCalendarsSection />);

    await screen.findByText('No calendars connected.');
    await userEvent.click(screen.getByRole('button', { name: /connect google calendar/i }));

    await waitFor(() => expect(mockedApi.connect).toHaveBeenCalledWith('google'));
    await waitFor(() => expect(window.location.href).toBe('https://accounts.google.com/o/oauth2/v2/auth?state=abc'));
  });

  it('disconnecting removes the connection from the list', async () => {
    mockedApi.listConnections.mockResolvedValue([CONNECTION]);
    mockedApi.disconnect.mockResolvedValue(undefined);
    render(<ExternalCalendarsSection />);

    await screen.findByText('Google Calendar');
    await userEvent.click(screen.getByRole('button', { name: /disconnect/i }));

    await waitFor(() => expect(mockedApi.disconnect).toHaveBeenCalledWith('conn-1'));
    expect(await screen.findByText('No calendars connected.')).toBeInTheDocument();
  });

  it('shows a success banner naming the provider when justConnectedProvider is set', async () => {
    mockedApi.listConnections.mockResolvedValue([]);
    render(<ExternalCalendarsSection justConnectedProvider="outlook" />);
    expect(await screen.findByText('Outlook Calendar connected.')).toBeInTheDocument();
  });

  it('shows an error banner when the connection list fails to load', async () => {
    mockedApi.listConnections.mockRejectedValue(new ApiError(500, 'internal_error', 'Something broke.'));
    render(<ExternalCalendarsSection />);
    expect(await screen.findByText('Something broke.')).toBeInTheDocument();
  });
});
