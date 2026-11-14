import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import timeGridPlugin from '@fullcalendar/timegrid';
import interactionPlugin from '@fullcalendar/interaction';
import type { DateSelectArg, DayHeaderContentArg, EventClickArg, FormatterInput } from '@fullcalendar/core';
import { ApiError, toApiError } from '../../api/client';
import { getSettings } from '../../api/settings';
import { TimezoneNotice } from '../../components/TimezoneNotice';
import { useDisplayPreferences } from '../../display/DisplayPreferences';
import { formatDayMonth, formatWeekday, type DateFormat, type TimeFormat } from '../../lib/dates';
import { listExternalEvents } from '../../api/externalEvents';
import { listInstances } from '../../api/taskInstances';
import { listProjections } from '../../api/taskTemplates';
import { OptimizeControls } from '../../optimization/OptimizeControls';
import { useOptimization } from '../../optimization/OptimizationContext';
import { buildCalendarEvents, type TimelineExtendedProps } from './buildEvents';
import { QuickCreatePanel } from './QuickCreatePanel';
import { SNAP_MINUTES, selectedSlot, selectionAllowed, type SlotSelection } from './quickCreate';
import type { BlackoutDate } from '../../types/settings';
import type { DayName, TaskInstance } from '../../types/task';
import type { ExternalEvent, VirtualOccurrence } from '../../types/timeline';

type LoadState = 'loading' | 'error' | 'ready';

/** FullCalendar's `firstDay` numbering (Sunday = 0) for the `first_day_of_week` setting. */
const FIRST_DAY_INDEX: Record<DayName, number> = {
  sunday: 0,
  monday: 1,
  tuesday: 2,
  wednesday: 3,
  thursday: 4,
  friday: 5,
  saturday: 6,
};

/** FullCalendar's own time labels (the hour axis, an event's time range) on the user's
 * clock: "17:00" / "17:30 - 18:30" on 24 hours, FullCalendar's "5pm" / "5:30 - 6:30" on 12. */
const SLOT_LABEL_FORMAT: Record<TimeFormat, FormatterInput> = {
  '24h': { hour: '2-digit', minute: '2-digit', hour12: false },
  '12h': { hour: 'numeric', meridiem: 'short' },
};
const EVENT_TIME_FORMAT: Record<TimeFormat, FormatterInput> = {
  '24h': { hour: '2-digit', minute: '2-digit', hour12: false },
  '12h': { hour: 'numeric', minute: '2-digit', meridiem: 'short' },
};

/** A time-grid column header: weekday plus day and month in the user's date format
 * ("Fri 13/11"). On a phone the CSS swaps the date for the bare day number, stacked under
 * the weekday - the month is already in the toolbar title, and seven "13/11"s don't fit.
 * The month grid keeps FullCalendar's plain weekday names. */
function dayHeader(arg: DayHeaderContentArg, dateFormat: DateFormat): JSX.Element | string {
  if (arg.view.type === 'dayGridMonth') return arg.text;
  return (
    <span className="fc-day-head">
      <span>{formatWeekday(arg.date)}</span> <span className="fc-day-head__date">{formatDayMonth(arg.date, dateFormat)}</span>
      <span className="fc-day-head__day">{arg.date.getDate()}</span>
    </span>
  );
}

/** Design doc §8.1 screen 2 / §9.2: calendar-style view of real `scheduled` instances
 * (and waiting fixed ones, drawn distinctly - Rev 10),
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
  // Reload when an optimization applied or undone changed the schedule under the page.
  const { scheduleRevision, locked } = useOptimization();
  const { dateFormat, timeFormat, firstDayOfWeek } = useDisplayPreferences();
  const [state, setState] = useState<LoadState>('loading');
  const [error, setError] = useState<ApiError | null>(null);
  const [instances, setInstances] = useState<TaskInstance[]>([]);
  const [projections, setProjections] = useState<VirtualOccurrence[]>([]);
  const [externalEvents, setExternalEvents] = useState<ExternalEvent[]>([]);
  const [blackoutDates, setBlackoutDates] = useState<BlackoutDate[]>([]);
  const [settingsTimezone, setSettingsTimezone] = useState<string | null>(null);
  // Quick create (design doc 8.1 screen 2, Rev 18): the selection being turned into a task.
  const [quick, setQuick] = useState<{ selection: SlotSelection; point: { x: number; y: number } | null } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const calendar = useRef<FullCalendar>(null);

  useEffect(() => {
    let cancelled = false;
    // Unfiltered: the Timeline shows `scheduled` instances and waiting (`blocked`) fixed
    // ones, and needs the others' names to label what those are waiting on.
    Promise.all([listInstances(), listProjections(), listExternalEvents(), getSettings()])
      .then(([loadedInstances, loadedProjections, loadedExternalEvents, settings]) => {
        if (cancelled) return;
        setInstances(loadedInstances);
        setProjections(loadedProjections);
        setExternalEvents(loadedExternalEvents);
        setBlackoutDates(settings.blackout_dates);
        setSettingsTimezone(settings.timezone);
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
  }, [scheduleRevision, reloadKey]);

  function handleSelect(arg: DateSelectArg): void {
    const pointer = arg.jsEvent as MouseEvent | null;
    const point = pointer && 'clientX' in pointer ? { x: pointer.clientX, y: pointer.clientY } : null;
    setQuick({ selection: { start: arg.start, end: arg.end }, point });
  }

  function closeQuickCreate(): void {
    setQuick(null);
    calendar.current?.getApi().unselect();
  }

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
      <OptimizeControls />
      <TimezoneNotice settingsTimezone={settingsTimezone} />
      {state === 'loading' ? (
        <p style={{ color: 'var(--color-text-muted)' }}>Loading...</p>
      ) : (
        <FullCalendar
          ref={calendar}
          plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
          initialView="timeGridWeek"
          headerToolbar={{ left: 'prev,next today', center: 'title', right: 'timeGridWeek,timeGridDay,dayGridMonth' }}
          events={events}
          eventClick={handleEventClick}
          firstDay={FIRST_DAY_INDEX[firstDayOfWeek]}
          dayHeaderContent={(arg) => dayHeader(arg, dateFormat)}
          slotLabelFormat={SLOT_LABEL_FORMAT[timeFormat]}
          eventTimeFormat={EVENT_TIME_FORMAT[timeFormat]}
          height="auto"
          nowIndicator
          // Quick create: empty time in the week/day grids only (a month cell has no time),
          // from now on, within one day; read-only while an optimization runs (6.11).
          selectable={!locked}
          selectMirror
          snapDuration={{ minutes: SNAP_MINUTES }}
          selectLongPressDelay={400}
          selectAllow={(span) => !span.allDay && selectionAllowed({ start: span.start, end: span.end })}
          unselectCancel=".quick-create"
          select={handleSelect}
        />
      )}
      {quick && (
        <QuickCreatePanel
          key={`${quick.selection.start.getTime()}-${quick.selection.end.getTime()}`}
          selection={quick.selection}
          slot={selectedSlot(quick.selection)}
          point={quick.point}
          onClose={closeQuickCreate}
          onCreated={() => {
            closeQuickCreate();
            setReloadKey((key) => key + 1);
          }}
          onOpenFullForm={(prefill) => navigate('/tasks/new', { state: { prefill } })}
        />
      )}
    </div>
  );
}
