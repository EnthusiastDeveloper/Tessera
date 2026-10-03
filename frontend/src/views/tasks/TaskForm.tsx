import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { DurationInput } from '../../components/DurationInput';
import { ScopePrompt } from '../../components/ScopePrompt';
import { ApiError, toApiError } from '../../api/client';
import { createTemplate, patchTemplateThisAndFuture } from '../../api/taskTemplates';
import type { CreateTemplatePayload, PatchTemplatePayload } from '../../api/taskTemplates';
import { listInstances, patchInstanceThisOccurrence } from '../../api/taskInstances';
import type { PatchInstancePayload } from '../../api/taskInstances';
import {
  DEADLINE_OFFSET_UNITS,
  ESTIMATED_DURATION_UNITS,
  offsetToEndOfDate,
} from '../../lib/duration';
import {
  MAX_DEADLINE_OFFSET_MINUTES,
  MAX_DESCRIPTION_LENGTH,
  MAX_DURATION_MINUTES,
  MAX_LOCATION_LENGTH,
  MAX_NAME_LENGTH,
  MAX_RECURRENCE_INTERVAL,
} from '../../lib/limits';
import type {
  ActiveHoursOverride,
  EditScope,
  Priority,
  RecurrenceAnchor,
  RecurrencePattern,
  TaskInstance,
  TaskTemplate,
  TaskType,
} from '../../types/task';
import { ActiveHoursOverrideInput } from './ActiveHoursOverrideInput';
import { DependenciesPicker } from './DependenciesPicker';
import { DurationListInput } from './DurationListInput';

const PRIORITIES: Priority[] = ['low', 'medium', 'high', 'critical'];
const PATTERNS: RecurrencePattern[] = ['one_time', 'daily', 'weekly', 'monthly'];
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

function toDatetimeLocal(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromDatetimeLocal(value: string): string {
  return new Date(value).toISOString();
}

const TERMINAL_STATUSES = new Set(['completed', 'dismissed']);

/** Occurrences a "this and future" edit from `edited` would skip by default: open ones
 * dated after it that were edited on their own (design doc §3.10, Rev 10). */
function skippedOccurrences(series: TaskInstance[], edited: TaskInstance): TaskInstance[] {
  const editedDate = edited.nominal_date ?? edited.generated_at;
  return series
    .filter(
      (occurrence) =>
        occurrence.id !== edited.id &&
        occurrence.detached &&
        !TERMINAL_STATUSES.has(occurrence.status) &&
        (occurrence.nominal_date ?? occurrence.generated_at) > editedDate
    )
    .sort((a, b) =>
      (a.nominal_date ?? a.generated_at) < (b.nominal_date ?? b.generated_at) ? -1 : 1
    );
}

function occurrenceLabel(occurrence: TaskInstance): string {
  return new Date(
    occurrence.scheduled_time ?? occurrence.nominal_date ?? occurrence.generated_at
  ).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
}

/** Drops null/undefined/'' so "unset" compares equal however each side spells it. */
function normalized(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(normalized);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([, v]) => v !== null && v !== undefined && v !== '')
        .sort(([a], [b]) => (a < b ? -1 : 1))
        .map(([k, v]) => [k, normalized(v)])
    );
  }
  return value === '' ? null : (value ?? null);
}

/** Only the fields that differ from the template - PATCH must be genuinely partial
 * (architecture-plan §5.1), and a field the user didn't touch must not be pushed onto
 * occurrences that kept their own value (design doc §3.10). */
function changedFields(
  payload: PatchTemplatePayload,
  template: TaskTemplate
): PatchTemplatePayload {
  const current = template as unknown as Record<string, unknown>;
  return Object.fromEntries(
    Object.entries(payload).filter(
      ([key, value]) =>
        value !== undefined &&
        JSON.stringify(normalized(value)) !== JSON.stringify(normalized(current[key]))
    )
  ) as PatchTemplatePayload;
}

/** Today as a local "YYYY-MM-DD" - the earliest start date a new task may take. */
function todayLocalDate(): string {
  return toDatetimeLocal(new Date().toISOString()).slice(0, 10);
}

interface TaskFormProps {
  mode: 'create' | 'edit';
  /** Required when `mode === 'edit'`. */
  template?: TaskTemplate;
  /** The live instance - required when `mode === 'edit'`, used as the "this occurrence"
   * PATCH target and to seed its own `deadline` (an absolute instant, distinct from the
   * template's relative `deadline_offset_minutes` - see design doc §3.10's field table). */
  instance?: TaskInstance;
  onSaved: (result: { template?: TaskTemplate; instance?: TaskInstance }) => void;
  onCancel: () => void;
}

export function TaskForm({
  mode,
  template,
  instance,
  onSaved,
  onCancel,
}: TaskFormProps): JSX.Element {
  const isEdit = mode === 'edit';
  const isRecurring = isEdit ? template!.recurrence.pattern !== 'one_time' : false;

  const [name, setName] = useState(template?.name ?? '');
  const [description, setDescription] = useState(template?.description ?? '');
  const [location, setLocation] = useState(template?.location ?? '');
  const [type, setType] = useState<TaskType>(template?.type ?? 'flexible');
  const [pattern, setPattern] = useState<RecurrencePattern>(
    template?.recurrence.pattern ?? 'one_time'
  );
  const [interval, setInterval_] = useState(template?.recurrence.interval ?? 1);
  const [dayOfWeek, setDayOfWeek] = useState(template?.recurrence.day_of_week ?? 0);
  const [dayOfMonth, setDayOfMonth] = useState(template?.recurrence.day_of_month ?? 1);
  const [anchor, setAnchor] = useState<RecurrenceAnchor>(template?.recurrence.anchor ?? 'calendar');
  const [startDate, setStartDate] = useState(todayLocalDate);
  const [fixedTimeOfDay, setFixedTimeOfDay] = useState(template?.fixed_time_of_day ?? '09:00');
  const [priority, setPriority] = useState<Priority>(template?.priority ?? 'medium');
  const [estimatedDurationMinutes, setEstimatedDurationMinutes] = useState(
    template?.estimated_duration_minutes ?? 30
  );
  const [deadlineOffsetMinutes, setDeadlineOffsetMinutes] = useState(
    template?.deadline_offset_minutes ?? 1440
  );
  // A one-time task may be given its deadline as a calendar date (IRR-2 M3). The date only
  // *sets* `deadlineOffsetMinutes`; the duration control stays the single source of truth,
  // and is remounted (`durationKey`) to show what the date resolved to.
  const [dueDate, setDueDate] = useState('');
  const [durationKey, setDurationKey] = useState(0);
  const [deadlineAt, setDeadlineAt] = useState(toDatetimeLocal(instance?.deadline));
  const [reminderOffsetsMinutes, setReminderOffsetsMinutes] = useState<number[]>(
    template?.reminder_offsets_minutes ?? []
  );
  const [activeHoursOverride, setActiveHoursOverride] = useState<ActiveHoursOverride | null>(
    template?.active_hours_override ?? null
  );
  const [dependencies, setDependencies] = useState<string[]>([]);

  const [scope, setScope] = useState<EditScope | null>(null);
  const [series, setSeries] = useState<TaskInstance[]>([]);
  const [includeDetached, setIncludeDetached] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // A one-time template has no "future occurrences" to distinguish (design doc §3.10) -
  // it always edits the template directly, with no prompt, exactly like create.
  const effectiveScope: EditScope | null = !isEdit
    ? null
    : !isRecurring
      ? 'this_and_future'
      : scope;
  const scopeChoicePending = isEdit && isRecurring && scope === null;
  // Template-only fields (recurrence, fixed_time_of_day, reminders, active-hours
  // override) never apply to a single occurrence (design doc §3.10's field table) - the
  // form hides them entirely rather than showing something that would silently no-op.
  const showTemplateOnlyFields = effectiveScope !== 'this_occurrence';
  const offersDueDate = !isEdit && pattern === 'one_time';
  const applyDueDate = (start: string, due: string): void => {
    setDueDate(due);
    setDeadlineOffsetMinutes(offsetToEndOfDate(start, due));
    setDurationKey((key) => key + 1);
  };
  const pickDueDate = (value: string): void => {
    if (value) applyDueDate(startDate, value);
    else setDueDate('');
  };
  // The picked due date is a calendar date, so moving the start date re-derives the offset
  // (and a start date past the due date drags the due date along with it).
  const changeStartDate = (value: string): void => {
    setStartDate(value);
    if (dueDate && value) applyDueDate(value, dueDate < value ? value : dueDate);
  };

  useEffect(() => {
    if (!isEdit || !isRecurring) return;
    let cancelled = false;
    listInstances({ template_id: template!.id })
      .then((occurrences) => {
        if (!cancelled) setSeries(occurrences);
      })
      .catch(() => {
        // Only the skipped-occurrences notice depends on this; the edit itself doesn't.
      });
    return () => {
      cancelled = true;
    };
  }, [isEdit, isRecurring, template]);

  const skipped = isEdit && isRecurring && instance ? skippedOccurrences(series, instance) : [];

  const handleSubmit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    if (scopeChoicePending) return;
    setError(null);
    setSubmitting(true);
    try {
      if (!isEdit) {
        const payload: CreateTemplatePayload = {
          name,
          type,
          recurrence: {
            pattern,
            anchor: type === 'flexible' ? anchor : 'calendar',
            ...(pattern !== 'one_time' ? { interval } : {}),
            ...(pattern === 'weekly' ? { day_of_week: dayOfWeek } : {}),
            ...(pattern === 'monthly' ? { day_of_month: dayOfMonth } : {}),
          },
          priority,
          estimated_duration_minutes: estimatedDurationMinutes,
          start_date: startDate,
          description: description || undefined,
          location: location || undefined,
          fixed_time_of_day: type === 'fixed' ? fixedTimeOfDay : undefined,
          deadline_offset_minutes: type === 'flexible' ? deadlineOffsetMinutes : undefined,
          reminder_offsets_minutes: reminderOffsetsMinutes,
          active_hours_override: activeHoursOverride,
          dependencies,
        };
        const result = await createTemplate(payload);
        onSaved({ template: result.template, instance: result.instance });
      } else if (effectiveScope === 'this_and_future') {
        const payload: PatchTemplatePayload = {
          name,
          description: description || undefined,
          location: location || undefined,
          priority,
          estimated_duration_minutes: estimatedDurationMinutes,
          fixed_time_of_day: type === 'fixed' ? fixedTimeOfDay : undefined,
          deadline_offset_minutes: type === 'flexible' ? deadlineOffsetMinutes : undefined,
          reminder_offsets_minutes: reminderOffsetsMinutes,
          active_hours_override: activeHoursOverride,
          recurrence: {
            pattern,
            anchor: type === 'flexible' ? anchor : 'calendar',
            ...(pattern !== 'one_time' ? { interval } : {}),
            ...(pattern === 'weekly' ? { day_of_week: dayOfWeek } : {}),
            ...(pattern === 'monthly' ? { day_of_month: dayOfMonth } : {}),
          },
        };
        const updated = await patchTemplateThisAndFuture(
          template!.id,
          changedFields(payload, template!),
          {
            // A one-time task has only its one occurrence; naming it would refuse an edit
            // once that occurrence is finished, when the template alone is still editable.
            fromInstanceId: isRecurring ? instance?.id : undefined,
            includeDetached: skipped.length > 0 && includeDetached,
          }
        );
        onSaved({ template: updated });
      } else {
        const payload: PatchInstancePayload = {
          name,
          description: description || undefined,
          location: location || undefined,
          priority,
          estimated_duration_minutes: estimatedDurationMinutes,
          ...(type === 'flexible' && deadlineAt ? { deadline: fromDatetimeLocal(deadlineAt) } : {}),
        };
        const updated = await patchInstanceThisOccurrence(instance!.id, payload);
        onSaved({ instance: updated });
      }
    } catch (err) {
      setError(toApiError(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={(event) => void handleSubmit(event)} noValidate>
      {error && (
        <div className="banner-error" role="alert">
          {error.message}
        </div>
      )}

      {isEdit && isRecurring && <ScopePrompt value={scope} onChange={setScope} />}

      {effectiveScope === 'this_and_future' && skipped.length > 0 && (
        <div className="field" role="note">
          <p>
            {skipped.length === 1
              ? '1 upcoming occurrence has its own changes and won’t be updated: '
              : `${skipped.length} upcoming occurrences have their own changes and won’t be updated: `}
            {skipped.map(occurrenceLabel).join(', ')}
          </p>
          <label>
            <input
              type="checkbox"
              checked={includeDetached}
              onChange={(event) => setIncludeDetached(event.target.checked)}
            />{' '}
            Apply to all upcoming occurrences, including these
          </label>
        </div>
      )}

      <div className="field">
        <label htmlFor="task-name">Name</label>
        <input
          id="task-name"
          type="text"
          value={name}
          maxLength={MAX_NAME_LENGTH}
          onChange={(event) => setName(event.target.value)}
          required
        />
      </div>

      <div className="field">
        <label htmlFor="task-description">Description</label>
        <input
          id="task-description"
          type="text"
          value={description}
          maxLength={MAX_DESCRIPTION_LENGTH}
          onChange={(event) => setDescription(event.target.value)}
        />
      </div>

      <div className="field">
        <label htmlFor="task-location">Location</label>
        <input
          id="task-location"
          type="text"
          value={location}
          maxLength={MAX_LOCATION_LENGTH}
          onChange={(event) => setLocation(event.target.value)}
        />
      </div>

      {!isEdit && (
        <fieldset className="field">
          <legend>Type</legend>
          <label style={{ marginRight: 'var(--space-4)' }}>
            <input
              type="radio"
              name="task-type"
              checked={type === 'flexible'}
              onChange={() => setType('flexible')}
            />{' '}
            Flexible
          </label>
          <label>
            <input
              type="radio"
              name="task-type"
              checked={type === 'fixed'}
              onChange={() => setType('fixed')}
            />{' '}
            Fixed
          </label>
        </fieldset>
      )}

      {!isEdit && (
        <div className="field">
          <label htmlFor="task-start-date">Starts on</label>
          <input
            id="task-start-date"
            type="date"
            value={startDate}
            min={todayLocalDate()}
            onChange={(event) => changeStartDate(event.target.value)}
            required
          />
          {error?.code === 'invalid_start_date' && <p className="field-error">{error.message}</p>}
        </div>
      )}

      {showTemplateOnlyFields && (
        <fieldset className="field">
          <legend>Recurrence</legend>
          <div className="field">
            <label htmlFor="task-pattern">Repeats</label>
            <select
              id="task-pattern"
              value={pattern}
              onChange={(event) => setPattern(event.target.value as RecurrencePattern)}
            >
              {PATTERNS.map((p) => (
                <option key={p} value={p}>
                  {p === 'one_time' ? 'Does not repeat' : p.charAt(0).toUpperCase() + p.slice(1)}
                </option>
              ))}
            </select>
          </div>
          {pattern !== 'one_time' && (
            <div className="field">
              <label htmlFor="task-interval">Every</label>
              <input
                id="task-interval"
                type="number"
                min={1}
                max={MAX_RECURRENCE_INTERVAL}
                value={interval}
                onChange={(event) => setInterval_(Number(event.target.value) || 1)}
              />
            </div>
          )}
          {pattern === 'weekly' && (
            <div className="field">
              <label htmlFor="task-day-of-week">On</label>
              <select
                id="task-day-of-week"
                value={dayOfWeek}
                onChange={(event) => setDayOfWeek(Number(event.target.value))}
              >
                {WEEKDAYS.map((day, index) => (
                  <option key={day} value={index}>
                    {day}
                  </option>
                ))}
              </select>
            </div>
          )}
          {pattern === 'monthly' && (
            <div className="field">
              <label htmlFor="task-day-of-month">Day of month</label>
              <input
                id="task-day-of-month"
                type="number"
                min={1}
                max={31}
                value={dayOfMonth}
                onChange={(event) => setDayOfMonth(Number(event.target.value) || 1)}
              />
            </div>
          )}
          {pattern !== 'one_time' && type === 'flexible' && (
            <div className="field">
              <label htmlFor="task-anchor">Next occurrence is based on</label>
              <select
                id="task-anchor"
                value={anchor}
                onChange={(event) => setAnchor(event.target.value as RecurrenceAnchor)}
              >
                <option value="calendar">The calendar (rigid schedule)</option>
                <option value="completion">When you complete it (upkeep work)</option>
              </select>
              {error?.code === 'invalid_recurrence_anchor' && (
                <p className="field-error">{error.message}</p>
              )}
            </div>
          )}
        </fieldset>
      )}

      {type === 'fixed' && showTemplateOnlyFields && (
        <div className="field">
          <label htmlFor="task-fixed-time">Time of day</label>
          <input
            id="task-fixed-time"
            type="time"
            value={fixedTimeOfDay}
            onChange={(event) => setFixedTimeOfDay(event.target.value)}
            required
          />
        </div>
      )}

      <div className="field">
        <label htmlFor="task-priority">Priority</label>
        <select
          id="task-priority"
          value={priority}
          onChange={(event) => setPriority(event.target.value as Priority)}
        >
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p.charAt(0).toUpperCase() + p.slice(1)}
            </option>
          ))}
        </select>
      </div>

      <DurationInput
        id="task-duration"
        label="Estimated duration"
        initialMinutes={estimatedDurationMinutes}
        units={ESTIMATED_DURATION_UNITS}
        onChange={setEstimatedDurationMinutes}
        min={1}
        maxMinutes={MAX_DURATION_MINUTES}
      />
      {error?.code === 'infeasible_duration' && <p className="field-error">{error.message}</p>}

      {type === 'flexible' && showTemplateOnlyFields && (
        <DurationInput
          key={durationKey}
          id="task-deadline-offset"
          label="Deadline"
          initialMinutes={deadlineOffsetMinutes}
          units={DEADLINE_OFFSET_UNITS}
          onChange={(minutes) => {
            setDeadlineOffsetMinutes(minutes);
            setDueDate('');
          }}
          min={1}
          maxMinutes={MAX_DEADLINE_OFFSET_MINUTES}
        />
      )}
      {type === 'flexible' && offersDueDate && (
        <div className="field">
          <label htmlFor="task-due-date">Or pick a due date</label>
          <input
            id="task-due-date"
            type="date"
            min={startDate}
            value={dueDate}
            onChange={(event) => pickDueDate(event.target.value)}
          />
        </div>
      )}
      {type === 'flexible' && showTemplateOnlyFields && (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)' }}>
          How long each occurrence may take to get done, counted from the start of its date.
        </p>
      )}

      {type === 'flexible' && !showTemplateOnlyFields && (
        <div className="field">
          <label htmlFor="task-deadline-at">Deadline</label>
          <input
            id="task-deadline-at"
            type="datetime-local"
            value={deadlineAt}
            onChange={(event) => setDeadlineAt(event.target.value)}
          />
        </div>
      )}

      {showTemplateOnlyFields && (
        <DurationListInput
          label="Reminders"
          values={reminderOffsetsMinutes}
          onChange={setReminderOffsetsMinutes}
        />
      )}

      {showTemplateOnlyFields && (
        <ActiveHoursOverrideInput value={activeHoursOverride} onChange={setActiveHoursOverride} />
      )}

      {!isEdit && <DependenciesPicker selected={dependencies} onChange={setDependencies} />}

      <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
        <button type="submit" className="primary" disabled={submitting || scopeChoicePending}>
          {submitting ? 'Saving…' : 'Save'}
        </button>
        <button type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
