import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { TimelinePage } from './TimelinePage';
import * as taskInstancesApi from '../../api/taskInstances';
import * as taskTemplatesApi from '../../api/taskTemplates';
import * as externalEventsApi from '../../api/externalEvents';
import * as settingsApi from '../../api/settings';
import type { TaskInstance } from '../../types/task';
import type { UserSettings } from '../../types/settings';
import type { ExternalEvent, VirtualOccurrence } from '../../types/timeline';

vi.mock('../../api/taskInstances');
vi.mock('../../api/taskTemplates');
vi.mock('../../api/externalEvents');
vi.mock('../../api/settings');

const mockedInstances = vi.mocked(taskInstancesApi);
const mockedTemplates = vi.mocked(taskTemplatesApi);
const mockedExternalEvents = vi.mocked(externalEventsApi);
const mockedSettings = vi.mocked(settingsApi);

// A fixed "now" the test suite's fake events are anchored around, so the default
// FullCalendar week view (initialView="timeGridWeek") actually contains them without
// this test file coupling itself to the real current date.
const TODAY = new Date();
function isoOnSameWeekAt(hour: number): string {
  const d = new Date(TODAY);
  d.setHours(hour, 0, 0, 0);
  return d.toISOString();
}

const REAL_INSTANCE: TaskInstance = {
  id: 'instance-1',
  template_id: 'template-1',
  name: 'Water the plants',
  description: null,
  location: null,
  type: 'flexible',
  priority: 2,
  estimated_duration_minutes: 30,
  detached: false,
  scheduled_time: isoOnSameWeekAt(9),
  deadline: null,
  status: 'scheduled',
  status_history: [],
  dependencies: [],
  completed_at: null,
  generated_at: '2026-01-01T00:00:00Z',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  version: 1,
};

const VIRTUAL_OCCURRENCE: VirtualOccurrence = {
  template_id: 'template-2',
  name: 'Weekly team sync',
  type: 'fixed',
  priority: 2,
  estimated_duration_minutes: 60,
  occurs_at: isoOnSameWeekAt(11),
  anchor: 'calendar',
};

const EXTERNAL_EVENT: ExternalEvent = {
  id: 'evt-1',
  connection_id: 'conn-1',
  provider_event_id: 'provider-evt-1',
  start: isoOnSameWeekAt(13),
  end: isoOnSameWeekAt(14),
  title: 'Dentist',
  is_all_day: false,
  is_transparent: false,
  fetched_at: '2026-01-01T00:00:00Z',
};

const SETTINGS: UserSettings = {
  id: 'settings-1',
  timezone: 'UTC',
  active_hours: {},
  blackout_dates: [],
  daily_time_budget_minutes: {},
  budget_enforcement: 'soft',
  first_day_of_week: 'monday',
};

function renderTimeline(): ReturnType<typeof render> {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<TimelinePage />} />
        <Route path="/tasks/:instanceId" element={<div>Task detail screen</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('TimelinePage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedInstances.listInstances.mockResolvedValue([REAL_INSTANCE]);
    mockedTemplates.listProjections.mockResolvedValue([VIRTUAL_OCCURRENCE]);
    mockedExternalEvents.listExternalEvents.mockResolvedValue([EXTERNAL_EVENT]);
    mockedSettings.getSettings.mockResolvedValue(SETTINGS);
  });

  it('requests scheduled instances, projections, external events, and settings on load', async () => {
    renderTimeline();
    await waitFor(() => expect(mockedInstances.listInstances).toHaveBeenCalledWith({ status: 'scheduled' }));
    expect(mockedTemplates.listProjections).toHaveBeenCalled();
    expect(mockedExternalEvents.listExternalEvents).toHaveBeenCalled();
    expect(mockedSettings.getSettings).toHaveBeenCalled();
  });

  it('renders the real instance as a clickable event that navigates to its detail page', async () => {
    renderTimeline();
    const realEvent = await screen.findByText('Water the plants');
    await userEvent.click(realEvent);
    await waitFor(() => expect(screen.getByText('Task detail screen')).toBeInTheDocument());
  });

  it('does not navigate when a virtual projection is clicked', async () => {
    renderTimeline();
    const ghostEvent = await screen.findByText('Weekly team sync');
    await userEvent.click(ghostEvent);
    // Give any (incorrect) navigation a chance to happen before asserting it didn't.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByText('Task detail screen')).not.toBeInTheDocument();
  });

  it('does not navigate when an external event is clicked', async () => {
    renderTimeline();
    const externalEvent = await screen.findByText('Dentist');
    await userEvent.click(externalEvent);
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.queryByText('Task detail screen')).not.toBeInTheDocument();
  });

  it('visually distinguishes the virtual projection from the real instance via CSS class', async () => {
    renderTimeline();
    const ghostEvent = await screen.findByText('Weekly team sync');
    const realEvent = await screen.findByText('Water the plants');
    const ghostEventEl = ghostEvent.closest('.fc-event');
    const realEventEl = realEvent.closest('.fc-event');
    expect(ghostEventEl).not.toBeNull();
    expect(realEventEl).not.toBeNull();
    expect(ghostEventEl?.classList.contains('fc-event-virtual')).toBe(true);
    expect(realEventEl?.classList.contains('fc-event-virtual')).toBe(false);
  });

  it('applies a distinct class to a completion-anchored projection (lower confidence, §9.2)', async () => {
    mockedTemplates.listProjections.mockResolvedValue([{ ...VIRTUAL_OCCURRENCE, anchor: 'completion' }]);
    renderTimeline();
    const ghostEvent = await screen.findByText('Weekly team sync');
    const ghostEventEl = ghostEvent.closest('.fc-event');
    expect(ghostEventEl?.classList.contains('fc-event-virtual--completion')).toBe(true);
  });

  it('marks an external event with its own visual class, distinct from a real instance', async () => {
    renderTimeline();
    const externalEvent = await screen.findByText('Dentist');
    const externalEventEl = externalEvent.closest('.fc-event');
    expect(externalEventEl?.classList.contains('fc-event-external')).toBe(true);
  });

  it('shows an error banner when loading fails', async () => {
    mockedInstances.listInstances.mockRejectedValue(new Error('network down'));
    renderTimeline();
    expect(await screen.findByText(/failed to load/i)).toBeInTheDocument();
  });
});
