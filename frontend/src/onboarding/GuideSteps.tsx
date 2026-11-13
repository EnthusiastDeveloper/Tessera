import { useState, type FormEvent, type ReactNode } from 'react';
import { DurationInput } from '../components/DurationInput';
import {
  DATE_FORMAT_OPTIONS,
  TIME_FORMAT_OPTIONS,
  formatDate,
  formatTime,
  formatWeekdayDayMonth,
  type DateFormat,
  type TimeFormat,
} from '../lib/dates';
import { DAY_LABELS, daysOfWeekFrom } from '../lib/days';
import { DAILY_BUDGET_UNITS } from '../lib/duration';
import { MAX_DAILY_BUDGET_MINUTES } from '../lib/limits';
import { availableTimezones, deviceTimezone, timezonesDiffer } from '../lib/timezone';
import type { ActiveHoursWindow, DayName } from '../types/task';
import type { BudgetEnforcement, UserSettings } from '../types/settings';
import {
  guideBudgetToDailyBudget,
  guideHoursToActiveHours,
  readGuideBudget,
  readGuideHours,
} from './guideSettings';

/** What every step gets from the guide: the current settings to prefill from, and the
 * three ways out - save and continue, skip (keep the current values) and back. */
export interface StepProps {
  settings: UserSettings;
  saving: boolean;
  onContinue: (patch: Partial<UserSettings>) => void;
  onSkip: () => void;
  onBack?: () => void;
}

const DEFAULT_BUDGET_MINUTES = 4 * 60;

const HOUR_PRESETS: ReadonlyArray<{ label: string; window: ActiveHoursWindow }> = [
  { label: 'Work hours', window: { start: '09:00', end: '17:00' } },
  { label: 'Evenings', window: { start: '18:00', end: '22:00' } },
];

function clock(hhmm: string, timeFormat: TimeFormat): string {
  const [hours, minutes] = hhmm.split(':').map(Number);
  return formatTime(new Date(2000, 0, 1, hours, minutes), timeFormat);
}

function StepLayout({
  title,
  intro,
  children,
  saving,
  onSubmit,
  onSkip,
  onBack,
  submitDisabled = false,
}: {
  title: string;
  intro: ReactNode;
  children: ReactNode;
  saving: boolean;
  onSubmit: () => void;
  onSkip: () => void;
  onBack?: () => void;
  submitDisabled?: boolean;
}): JSX.Element {
  const handleSubmit = (event: FormEvent): void => {
    event.preventDefault();
    onSubmit();
  };
  return (
    <form onSubmit={handleSubmit} noValidate>
      <h1 className="mb-2 text-2xl">{title}</h1>
      <p className="mb-6 text-text-muted">{intro}</p>
      {children}
      <div className="mt-8 flex flex-wrap items-center gap-3">
        {onBack && (
          <button type="button" onClick={onBack} disabled={saving}>
            Back
          </button>
        )}
        <div className="flex-1" />
        <button type="button" onClick={onSkip} disabled={saving}>
          Skip
        </button>
        <button type="submit" className="primary" disabled={saving || submitDisabled}>
          {saving ? 'Saving…' : 'Continue'}
        </button>
      </div>
    </form>
  );
}

export function TimezoneStep({
  settings,
  saving,
  onContinue,
  onSkip,
  onBack,
}: StepProps): JSX.Element {
  const [timezone, setTimezone] = useState(settings.timezone);
  const [timezones] = useState<string[]>(availableTimezones);
  const device = deviceTimezone();
  return (
    <StepLayout
      title="Your timezone"
      intro="Tessera uses it to work out when your days start and end."
      saving={saving}
      onSubmit={() => onContinue({ timezone })}
      onSkip={onSkip}
      onBack={onBack}
    >
      <div className="field">
        <label htmlFor="guide-timezone">Timezone</label>
        <select
          id="guide-timezone"
          value={timezone}
          onChange={(event) => setTimezone(event.target.value)}
        >
          {!timezones.includes(timezone) && <option value={timezone}>{timezone}</option>}
          {timezones.map((tz) => (
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </select>
      </div>
      {timezonesDiffer(device, timezone) && (
        <p className="flex flex-wrap items-center gap-3 text-sm text-text-muted">
          Your browser says you&apos;re in {device}.
          <button type="button" onClick={() => setTimezone(device)}>
            Switch to {device}
          </button>
        </p>
      )}
    </StepLayout>
  );
}

export function WeekStep({ settings, saving, onContinue, onSkip, onBack }: StepProps): JSX.Element {
  const [firstDayOfWeek, setFirstDayOfWeek] = useState<DayName>(settings.first_day_of_week);
  const [dateFormat, setDateFormat] = useState<DateFormat>(settings.date_format);
  const [timeFormat, setTimeFormat] = useState<TimeFormat>(settings.time_format);
  const [now] = useState(() => new Date());
  return (
    <StepLayout
      title="Your week"
      intro="Where your week starts, and how dates and times are shown."
      saving={saving}
      onSubmit={() =>
        onContinue({
          first_day_of_week: firstDayOfWeek,
          date_format: dateFormat,
          time_format: timeFormat,
        })
      }
      onSkip={onSkip}
      onBack={onBack}
    >
      <div className="field">
        <label htmlFor="guide-first-day">First day of the week</label>
        <select
          id="guide-first-day"
          value={firstDayOfWeek}
          onChange={(event) => setFirstDayOfWeek(event.target.value as DayName)}
        >
          {daysOfWeekFrom('sunday').map((day) => (
            <option key={day} value={day}>
              {DAY_LABELS[day]}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="guide-date-format">Date format</label>
        <select
          id="guide-date-format"
          value={dateFormat}
          onChange={(event) => setDateFormat(event.target.value as DateFormat)}
        >
          {DATE_FORMAT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="guide-time-format">Time format</label>
        <select
          id="guide-time-format"
          value={timeFormat}
          onChange={(event) => setTimeFormat(event.target.value as TimeFormat)}
        >
          {TIME_FORMAT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <p className="text-sm text-text-muted" data-testid="guide-date-example">
        Right now that&apos;s {formatWeekdayDayMonth(now, dateFormat)},{' '}
        {formatTime(now, timeFormat)}({formatDate(now, dateFormat)}).
      </p>
    </StepLayout>
  );
}

export function HoursStep({
  settings,
  saving,
  onContinue,
  onSkip,
  onBack,
}: StepProps): JSX.Element {
  const [initial] = useState(() => readGuideHours(settings.active_hours));
  const [days, setDays] = useState<DayName[]>(initial.days);
  const [hours, setHours] = useState<ActiveHoursWindow>(initial.window);
  const timeFormat = settings.time_format;

  const toggleDay = (day: DayName): void =>
    setDays((current) =>
      current.includes(day) ? current.filter((d) => d !== day) : [...current, day]
    );

  return (
    <StepLayout
      title="When should Tessera schedule tasks?"
      intro="First, a quick word on the two kinds of task you can add."
      saving={saving}
      submitDisabled={days.length === 0}
      onSubmit={() => onContinue({ active_hours: guideHoursToActiveHours(days, hours) })}
      onSkip={onSkip}
      onBack={onBack}
    >
      {/* The first step where the difference matters (design doc 8.1 screen 0a): name both
          kinds in the Timeline's own colors before asking anything that depends on it. */}
      <dl
        className="mb-6 grid gap-3 rounded-md border border-border bg-surface-raised p-4 text-sm"
        aria-label="Kinds of task"
      >
        <div>
          <dt className="font-semibold text-fixed">Fixed</dt>
          <dd className="m-0 text-text-muted">
            Has a set time, like a dentist appointment. It stays where you put it, even outside the
            hours you pick below.
          </dd>
        </div>
        <div>
          <dt className="font-semibold text-flexible-strong">Flexible</dt>
          <dd className="m-0 text-text-muted">
            Has a length and a due date, like &quot;write the report, 2 hours, by Friday&quot;.
            Tessera picks the time for you, on the days and hours below. If a fixed task later needs
            that slot, Tessera moves the flexible one somewhere else.
          </dd>
        </div>
      </dl>
      <fieldset className="field">
        <legend>Days</legend>
        <div className="flex flex-wrap gap-2">
          {daysOfWeekFrom(settings.first_day_of_week).map((day) => {
            const on = days.includes(day);
            return (
              <button
                key={day}
                type="button"
                aria-pressed={on}
                aria-label={DAY_LABELS[day]}
                onClick={() => toggleDay(day)}
                className={
                  on
                    ? 'min-w-14 border-accent bg-accent text-accent-contrast hover:bg-accent'
                    : 'min-w-14 text-text-muted'
                }
              >
                {DAY_LABELS[day].slice(0, 3)}
              </button>
            );
          })}
        </div>
        {days.length === 0 && <p className="field-error">Pick at least one day.</p>}
      </fieldset>

      <fieldset className="field">
        <legend>Hours</legend>
        <div className="mb-3 flex flex-wrap gap-2">
          {HOUR_PRESETS.map((preset) => {
            const on = preset.window.start === hours.start && preset.window.end === hours.end;
            return (
              <button
                key={preset.label}
                type="button"
                aria-pressed={on}
                onClick={() => setHours(preset.window)}
                className={`px-3 text-sm ${on ? 'border-accent text-accent' : ''}`}
              >
                {preset.label} · {clock(preset.window.start, timeFormat)} -{' '}
                {clock(preset.window.end, timeFormat)}
              </button>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="time"
            aria-label="From"
            value={hours.start}
            onChange={(event) => setHours((current) => ({ ...current, start: event.target.value }))}
          />
          <span>to</span>
          <input
            type="time"
            aria-label="Until"
            value={hours.end}
            onChange={(event) => setHours((current) => ({ ...current, end: event.target.value }))}
          />
          {hours.end < hours.start && (
            <span className="text-sm text-text-muted">(ends next day)</span>
          )}
        </div>
      </fieldset>

      {!initial.uniform && (
        <div className="banner-warning" role="note">
          Your days don&apos;t all have the same hours at the moment. If you continue, they will.
          Press Skip to leave them alone.
        </div>
      )}
      <p className="text-sm text-text-muted">
        Need different hours on different days? You can set that up in Settings later.
      </p>
    </StepLayout>
  );
}

export function BudgetStep({
  settings,
  saving,
  onContinue,
  onSkip,
  onBack,
}: StepProps): JSX.Element {
  const [initial] = useState(() => readGuideBudget(settings.daily_time_budget_minutes));
  const [limited, setLimited] = useState(initial.minutes !== null);
  const [minutes, setMinutes] = useState(initial.minutes ?? DEFAULT_BUDGET_MINUTES);
  const [enforcement, setEnforcement] = useState<BudgetEnforcement>(settings.budget_enforcement);
  const invalid = limited && (minutes <= 0 || minutes > MAX_DAILY_BUDGET_MINUTES);

  return (
    <StepLayout
      title="Your daily budget"
      intro="A daily budget caps how much work Tessera lets a single day hold. Fixed tasks and calendar events count toward it, but are never moved because of it: it only limits the flexible work Tessera adds."
      saving={saving}
      submitDisabled={invalid}
      onSubmit={() =>
        onContinue({
          daily_time_budget_minutes: guideBudgetToDailyBudget(limited ? minutes : null),
          budget_enforcement: enforcement,
        })
      }
      onSkip={onSkip}
      onBack={onBack}
    >
      <fieldset className="field">
        <legend>Daily budget</legend>
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="guide-budget"
            checked={!limited}
            onChange={() => setLimited(false)}
          />
          No daily budget
        </label>
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="guide-budget"
            checked={limited}
            onChange={() => setLimited(true)}
          />
          Set a daily budget
        </label>
        {limited && (
          <div className="mt-2 pl-6">
            <DurationInput
              id="guide-budget-amount"
              label="At most, per day"
              initialMinutes={minutes}
              units={DAILY_BUDGET_UNITS}
              onChange={setMinutes}
              maxMinutes={MAX_DAILY_BUDGET_MINUTES}
            />
            {invalid && (
              <p className="field-error">Enter a budget between 1 minute and 24 hours.</p>
            )}
          </div>
        )}
      </fieldset>

      {limited && (
        <fieldset className="field">
          <legend>
            If a flexible task won&apos;t fit in the daily budget before it&apos;s due
          </legend>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="guide-enforcement"
              checked={enforcement === 'soft'}
              onChange={() => setEnforcement('soft')}
            />
            Go over the budget so it&apos;s done on time
          </label>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="guide-enforcement"
              checked={enforcement === 'strict'}
              onChange={() => setEnforcement('strict')}
            />
            Keep to the budget and leave the task unscheduled
          </label>
        </fieldset>
      )}

      {!initial.uniform && (
        <div className="banner-warning" role="note">
          Your days have different budgets at the moment. If you continue, they&apos;ll all get this
          one. Press Skip to leave them alone.
        </div>
      )}
    </StepLayout>
  );
}

export function DoneStep({ onNavigate }: { onNavigate: (to: string) => void }): JSX.Element {
  return (
    <div>
      <h1 className="mb-2 text-2xl">That&apos;s it</h1>
      <p className="mb-6 text-text-muted">
        Your settings are saved, and you can change them any time in Settings.
      </p>
      <div className="flex flex-wrap gap-3">
        <button type="button" className="primary" onClick={() => onNavigate('/tasks/new')}>
          Add your first task
        </button>
        <button type="button" onClick={() => onNavigate('/')}>
          Go to the Timeline
        </button>
      </div>
      <p className="mt-6 text-sm text-text-muted">
        Days off and calendar connections (Google, Outlook) are in{' '}
        <a
          href="/settings"
          onClick={(event) => {
            event.preventDefault();
            onNavigate('/settings');
          }}
        >
          Settings
        </a>
        .
      </p>
    </div>
  );
}
