import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import timeGridPlugin from '@fullcalendar/timegrid';
import type { EventClickArg } from '@fullcalendar/core';
import { ApiError, toApiError } from '../../api/client';
import { getSettings } from '../../api/settings';
import { listExternalEvents } from '../../api/externalEvents';
import { listInstances } from '../../api/taskInstances';
import { listProjections } from '../../api/taskTemplates';
import { buildCalendarEvents, type TimelineExtendedProps } from './buildEvents';
import type { BlackoutDate } from '../../types/settings';
import type { TaskInstance } from '../../types/task';
import type { ExternalEvent, VirtualOccurrence } from '../../types/timeline';

type LoadState = 'loading' | 'error' | 'ready';

/** Design doc §8.1 screen 2 / §9.2: calendar-style view of real `scheduled` instances,
 * plus display-only virtual "ghost" projections of upcoming recurring occurrences,
 * external busy-blocks (post-filtering per §7), and blackout dates.
 *
 * **View choice (documented per implementation-plan Stage 9d's "pick one, don't leave it
 * implicit" instruction, mirrored in the PR body):** default view is `timeGridWeek`, not
 * `dayGridMonth`. The app's entire value proposition (design doc §6.2) is precise
 * *time* placement inside active-hours windows on a 15-minute grid - a month grid shows
 * which day a task landed on but not when, which is exactly the information a user needs
 * to see their day actually fill up. `dayGridMonth` is kept as a one-click toggle
 * (FullCalendar's built-in header toolbar) specifically because §9.2's ghost horizon is
 * 30 days - a week view alone would need four-plus manual page-forwards to see the whole
 * horizon at a glance.
 *
 * Real instances are the only interactive layer (`eventClick` navigates to
 * `TaskDetailPage` only when `extendedProps.kind === 'real'`) - virtual projections,
 * external events, and blackout ranges are display-only per §9.2/§7 and never navigate.
 */
export function TimelinePage(): JSX.Element {
  const navigate = useNavigate();
  const [state, setState] = useState<LoadState>('loading');
  const [error, setError] = useState<ApiError | null>(null);
  const [instances, setInstances] = useState<TaskInstance[]>([]);
  const [projections, setProjections] = useState<VirtualOccurrence[]>([]);
  const [externalEvents, setExternalEvents] = useState<ExternalEvent[]>([]);
  const [blackoutDates, setBlackoutDates] = useState<BlackoutDate[]>([]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listInstances({ status: 'scheduled' }), listProjections(), listExternalEvents(), getSettings()])
      .then(([loadedInstances, loadedProjections, loadedExternalEvents, settings]) => {
        if (cancelled) return;
        setInstances(loadedInstances);
        setProjections(loadedProjections);
        setExternalEvents(loadedExternalEvents);
        setBlackoutDates(settings.blackout_dates);
        setState('ready');
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(toApiError(err, new ApiError(500, 'unknown_error', 'Failed to load the Timeline.')));
        setState('error');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function handleEventClick(arg: EventClickArg): void {
    const props = arg.event.extendedProps as TimelineExtendedProps;
    if (props.kind === 'real' && props.instanceId) {
      navigate(`/tasks/${props.instanceId}`);
    }
    // virtual/external/blackout: intentionally no-op - §9.2 "cannot be marked complete,
    // rescheduled, or otherwise interacted with"; §7 external sync is read-only.
  }

  if (state === 'error') {
    return (
      <div>
        <h2>Timeline</h2>
        <div className="banner-error">{error?.message ?? 'Failed to load the Timeline.'}</div>
      </div>
    );
  }

  const events = buildCalendarEvents({ instances, projections, externalEvents, blackoutDates });

  return (
    <div>
      <h2>Timeline</h2>
      {state === 'loading' ? (
        <p style={{ color: 'var(--color-text-muted)' }}>Loading...</p>
      ) : (
        <FullCalendar
          plugins={[dayGridPlugin, timeGridPlugin]}
          initialView="timeGridWeek"
          headerToolbar={{ left: 'prev,next today', center: 'title', right: 'timeGridWeek,timeGridDay,dayGridMonth' }}
          events={events}
          eventClick={handleEventClick}
          height="auto"
          nowIndicator
        />
      )}
    </div>
  );
}
