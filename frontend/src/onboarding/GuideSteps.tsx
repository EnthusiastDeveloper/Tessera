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
  { label: 'Working hours', window: { start: '09:00', end: '17:00' } },
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
      title="Where are you?"
      intro="Tessera plans your days in this timezone. Moving later changes nothing already on your calendar."
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
          This device is set to {device}.
          <button type="button" onClick={() => setTimezone(device)}>
            Use {device}
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
      intro="How the calendar is laid out and how dates and times are written. This only changes what you see, never what gets scheduled."
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
        Right now reads as {formatWeekdayDayMonth(now, dateFormat)}, {formatDate(now, dateFormat)}{' '}
        {formatTime(now, timeFormat)}.
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
      title="When can Tessera schedule work?"
      intro="Tessera has two kinds of task, and these hours are for one of them."
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
            Happens at a time you choose - a meeting, a class, a train. Tessera keeps it exactly
            there, on any day and at any hour, and plans around it.
          </dd>
        </div>
        <div>
          <dt className="font-semibold text-flexible-strong">Flexible</dt>
          <dd className="m-0 text-text-muted">
            Needs doing by a deadline, not at a set time - write a report, do the shopping. You say
            how long it takes and by when; Tessera finds the time, only on the days and hours below,
            and finds it a new place if something fixed takes its slot.
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
          Your days currently have different hours. Continuing gives every chosen day the hours
          above; skip to keep them as they are.
        </div>
      )}
      <p className="text-sm text-text-muted">
        Different hours on different days, a split day or an evening that runs past midnight can be
        set in Settings.
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
      title="How much flexible work a day?"
      intro="A daily budget caps how much flexible work Tessera places on one day, so it doesn't fill every free minute. Fixed tasks don't count against it."
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
          No limit
        </label>
        <label className="flex items-center gap-2">
          <input
            type="radio"
            name="guide-budget"
            checked={limited}
            onChange={() => setLimited(true)}
          />
          Limit it
        </label>
        {limited && (
          <div className="mt-2 pl-6">
            <DurationInput
              id="guide-budget-amount"
              label="Up to, per day"
              initialMinutes={minutes}
              units={DAILY_BUDGET_UNITS}
              onChange={setMinutes}
              maxMinutes={MAX_DAILY_BUDGET_MINUTES}
            />
            {invalid && (
              <p className="field-error">Pick an amount between a minute and 24 hours.</p>
            )}
          </div>
        )}
      </fieldset>

      {limited && (
        <fieldset className="field">
          <legend>When a deadline can't be met within the budget</legend>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="guide-enforcement"
              checked={enforcement === 'soft'}
              onChange={() => setEnforcement('soft')}
            />
            Meet the deadline - go over the budget as a last resort
          </label>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              name="guide-enforcement"
              checked={enforcement === 'strict'}
              onChange={() => setEnforcement('strict')}
            />
            Respect the budget - leave the task unscheduled instead
          </label>
        </fieldset>
      )}

      {!initial.uniform && (
        <div className="banner-warning" role="note">
          Your days currently have different budgets. Continuing gives every day the same one; skip
          to keep them as they are.
        </div>
      )}
    </StepLayout>
  );
}

export function DoneStep({ onNavigate }: { onNavigate: (to: string) => void }): JSX.Element {
  return (
    <div>
      <h1 className="mb-2 text-2xl">You&apos;re all set</h1>
      <p className="mb-6 text-text-muted">
        Add a task and Tessera finds it a place. You can change any of this later in Settings.
      </p>
      <div className="flex flex-wrap gap-3">
        <button type="button" className="primary" onClick={() => onNavigate('/tasks/new')}>
          Create your first task
        </button>
        <button type="button" onClick={() => onNavigate('/')}>
          Go to the Timeline
        </button>
      </div>
      <p className="mt-6 text-sm text-text-muted">
        Taking days off, or want your other calendars to block time?{' '}
        <a
          href="/settings"
          onClick={(event) => {
            event.preventDefault();
            onNavigate('/settings');
          }}
        >
          Add days off or connect a calendar in Settings
        </a>
        .
      </p>
    </div>
  );
}
