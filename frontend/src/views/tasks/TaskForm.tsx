import { useState } from 'react';
import type { FormEvent } from 'react';
import { DurationInput } from '../../components/DurationInput';
import { ScopePrompt } from '../../components/ScopePrompt';
import { ApiError } from '../../api/client';
import { createTemplate, patchTemplateThisAndFuture } from '../../api/taskTemplates';
import type { CreateTemplatePayload, PatchTemplatePayload } from '../../api/taskTemplates';
import { patchInstanceThisOccurrence } from '../../api/taskInstances';
import type { PatchInstancePayload } from '../../api/taskInstances';
import { DEADLINE_OFFSET_UNITS, ESTIMATED_DURATION_UNITS } from '../../lib/duration';
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

const PRIORITY_TO_NUMBER: Record<Priority, number> = { low: 1, medium: 2, high: 3, critical: 4 };
const PRIORITIES: Priority[] = ['low', 'medium', 'high', 'critical'];
const PATTERNS: RecurrencePattern[] = ['one_time', 'daily', 'weekly', 'monthly', 'custom'];
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

export function TaskForm({ mode, template, instance, onSaved, onCancel }: TaskFormProps): JSX.Element {
  const isEdit = mode === 'edit';
  const isRecurring = isEdit ? template!.recurrence.pattern !== 'one_time' : false;

  const [name, setName] = useState(template?.name ?? '');
  const [description, setDescription] = useState(template?.description ?? '');
  const [location, setLocation] = useState(template?.location ?? '');
  const [type, setType] = useState<TaskType>(template?.type ?? 'flexible');
  const [pattern, setPattern] = useState<RecurrencePattern>(template?.recurrence.pattern ?? 'one_time');
  const [interval, setInterval_] = useState(template?.recurrence.interval ?? 1);
  const [dayOfWeek, setDayOfWeek] = useState(template?.recurrence.day_of_week ?? 0);
  const [dayOfMonth, setDayOfMonth] = useState(template?.recurrence.day_of_month ?? 1);
  const [anchor, setAnchor] = useState<RecurrenceAnchor>(template?.recurrence.anchor ?? 'calendar');
  const [fixedTimeOfDay, setFixedTimeOfDay] = useState(template?.fixed_time_of_day ?? '09:00');
  const [priority, setPriority] = useState<Priority>(template?.priority ?? 'medium');
  const [estimatedDurationMinutes, setEstimatedDurationMinutes] = useState(template?.estimated_duration_minutes ?? 30);
  const [deadlineOffsetMinutes, setDeadlineOffsetMinutes] = useState(template?.deadline_offset_minutes ?? 1440);
  const [deadlineAt, setDeadlineAt] = useState(toDatetimeLocal(instance?.deadline));
  const [reminderOffsetsMinutes, setReminderOffsetsMinutes] = useState<number[]>(template?.reminder_offsets_minutes ?? []);
  const [activeHoursOverride, setActiveHoursOverride] = useState<ActiveHoursOverride | null>(
    template?.active_hours_override ?? null
  );
  const [dependencies, setDependencies] = useState<string[]>([]);

  const [scope, setScope] = useState<EditScope | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // A one-time template has no "future occurrences" to distinguish (design doc §3.10) -
  // it always edits the template directly, with no prompt, exactly like create.
  const effectiveScope: EditScope | null = !isEdit ? null : !isRecurring ? 'this_and_future' : scope;
  const scopeChoicePending = isEdit && isRecurring && scope === null;
  // Template-only fields (recurrence, fixed_time_of_day, reminders, active-hours
  // override) never apply to a single occurrence (design doc §3.10's field table) - the
  // form hides them entirely rather than showing something that would silently no-op.
  const showTemplateOnlyFields = effectiveScope !== 'this_occurrence';

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
        const updated = await patchTemplateThisAndFuture(template!.id, payload);
        onSaved({ template: updated });
      } else {
        const payload: PatchInstancePayload = {
          name,
          description: description || undefined,
          location: location || undefined,
          priority: PRIORITY_TO_NUMBER[priority],
          estimated_duration_minutes: estimatedDurationMinutes,
          ...(type === 'flexible' && deadlineAt ? { deadline: fromDatetimeLocal(deadlineAt) } : {}),
        };
        const updated = await patchInstanceThisOccurrence(instance!.id, payload);
        onSaved({ instance: updated });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError(0, 'network_error', 'Could not reach the server.'));
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

      <div className="field">
        <label htmlFor="task-name">Name</label>
        <input id="task-name" type="text" value={name} onChange={(event) => setName(event.target.value)} required />
      </div>

      <div className="field">
        <label htmlFor="task-description">Description</label>
        <input id="task-description" type="text" value={description} onChange={(event) => setDescription(event.target.value)} />
      </div>

      <div className="field">
        <label htmlFor="task-location">Location</label>
        <input id="task-location" type="text" value={location} onChange={(event) => setLocation(event.target.value)} />
      </div>

      {!isEdit && (
        <fieldset className="field">
          <legend>Type</legend>
          <label style={{ marginRight: 'var(--space-4)' }}>
            <input type="radio" name="task-type" checked={type === 'flexible'} onChange={() => setType('flexible')} /> Flexible
          </label>
          <label>
            <input type="radio" name="task-type" checked={type === 'fixed'} onChange={() => setType('fixed')} /> Fixed
          </label>
        </fieldset>
      )}

      {showTemplateOnlyFields && (
        <fieldset className="field">
          <legend>Recurrence</legend>
          <div className="field">
            <label htmlFor="task-pattern">Repeats</label>
            <select id="task-pattern" value={pattern} onChange={(event) => setPattern(event.target.value as RecurrencePattern)}>
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
                value={interval}
                onChange={(event) => setInterval_(Number(event.target.value) || 1)}
              />
            </div>
          )}
          {pattern === 'weekly' && (
            <div className="field">
              <label htmlFor="task-day-of-week">On</label>
              <select id="task-day-of-week" value={dayOfWeek} onChange={(event) => setDayOfWeek(Number(event.target.value))}>
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
              <select id="task-anchor" value={anchor} onChange={(event) => setAnchor(event.target.value as RecurrenceAnchor)}>
                <option value="calendar">The calendar (rigid schedule)</option>
                <option value="completion">When you complete it (upkeep work)</option>
              </select>
              {error?.code === 'invalid_recurrence_anchor' && <p className="field-error">{error.message}</p>}
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
        <select id="task-priority" value={priority} onChange={(event) => setPriority(event.target.value as Priority)}>
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
      />
      {error?.code === 'infeasible_duration' && <p className="field-error">{error.message}</p>}

      {type === 'flexible' && showTemplateOnlyFields && (
        <DurationInput
          id="task-deadline-offset"
          label="Deadline"
          initialMinutes={deadlineOffsetMinutes}
          units={DEADLINE_OFFSET_UNITS}
          onChange={setDeadlineOffsetMinutes}
          min={1}
        />
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
        <DurationListInput label="Reminders" values={reminderOffsetsMinutes} onChange={setReminderOffsetsMinutes} />
      )}

      {showTemplateOnlyFields && <ActiveHoursOverrideInput value={activeHoursOverride} onChange={setActiveHoursOverride} />}

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
