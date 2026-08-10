import { useState } from 'react';
import { DayOfWeekRows } from '../../components/DayOfWeekRows';
import { DurationInput } from '../../components/DurationInput';
import { updateSettings } from '../../api/settings';
import { ApiError } from '../../api/client';
import { DAILY_BUDGET_UNITS } from '../../lib/duration';
import { DAY_LABELS } from '../../lib/days';
import type { ActiveHoursWindow, DayName } from '../../types/task';
import type { BlackoutDate, BudgetEnforcement, UserSettings } from '../../types/settings';

const DEFAULT_WINDOW: ActiveHoursWindow = { start: '09:00', end: '17:00' };
const DEFAULT_BUDGET_MINUTES = 120;

type ActiveHoursMode = 'excluded' | 'custom';

function activeHoursMode(window: ActiveHoursWindow | null | undefined): ActiveHoursMode {
  return window ? 'custom' : 'excluded';
}

interface SchedulingWindowSectionProps {
  settings: UserSettings;
  onUpdated: (settings: UserSettings) => void;
}

/** §8.1 screen 6 "Scheduling window": global active-hours per day of week, blackout
 * dates list, daily time-budget cap per day of week, and the budget-enforcement toggle
 * (§3.7, §6.2). One `PATCH /settings` call saves the whole section together - unlike
 * `active_hours_override` (§3.2, task form), `UserSettings.active_hours` has no
 * "inherit" state to represent (every day is either an explicit window or explicitly
 * excluded, §3.7's own "null always means day excluded" rule), so this control offers
 * only those two modes.
 */
export function SchedulingWindowSection({ settings, onUpdated }: SchedulingWindowSectionProps): JSX.Element {
  const [activeHours, setActiveHours] = useState<Record<DayName, ActiveHoursWindow | null>>(
    settings.active_hours as Record<DayName, ActiveHoursWindow | null>
  );
  const [dailyBudget, setDailyBudget] = useState<Record<DayName, number | null>>(
    settings.daily_time_budget_minutes as Record<DayName, number | null>
  );
  const [budgetEnforcement, setBudgetEnforcement] = useState<BudgetEnforcement>(settings.budget_enforcement);
  const [blackoutDates, setBlackoutDates] = useState<BlackoutDate[]>(settings.blackout_dates);
  const [newBlackoutStart, setNewBlackoutStart] = useState('');
  const [newBlackoutEnd, setNewBlackoutEnd] = useState('');
  const [newBlackoutLabel, setNewBlackoutLabel] = useState('');
  const [blackoutError, setBlackoutError] = useState<string | null>(null);

  const [bannerError, setBannerError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const setActiveHoursDay = (day: DayName, mode: ActiveHoursMode, window?: ActiveHoursWindow): void => {
    setActiveHours((prev) => ({ ...prev, [day]: mode === 'excluded' ? null : (window ?? prev[day] ?? DEFAULT_WINDOW) }));
  };

  const setDailyBudgetDay = (day: DayName, minutes: number | null): void => {
    setDailyBudget((prev) => ({ ...prev, [day]: minutes }));
  };

  const addBlackoutDate = (): void => {
    setBlackoutError(null);
    if (!newBlackoutStart || !newBlackoutEnd) {
      setBlackoutError('Start and end dates are required.');
      return;
    }
    if (newBlackoutEnd < newBlackoutStart) {
      setBlackoutError('End date must be on or after the start date.');
      return;
    }
    setBlackoutDates((prev) => [
      ...prev,
      { start: newBlackoutStart, end: newBlackoutEnd, label: newBlackoutLabel || null },
    ]);
    setNewBlackoutStart('');
    setNewBlackoutEnd('');
    setNewBlackoutLabel('');
  };

  const removeBlackoutDate = (index: number): void => {
    setBlackoutDates((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSave = async (): Promise<void> => {
    setBannerError(null);
    setSuccessMessage(null);
    setSaving(true);
    try {
      // active_hours/daily_time_budget_minutes must be sent as a complete 7-day map
      // whenever the key is present at all (backend's `_validate_full_week`) - both
      // maps here are always fully populated by construction (every day was seeded
      // from the loaded settings and every mutation above updates in place, never
      // deletes a key), so no extra reconciliation is needed before sending.
      const updated = await updateSettings({
        active_hours: activeHours,
        daily_time_budget_minutes: dailyBudget,
        budget_enforcement: budgetEnforcement,
        blackout_dates: blackoutDates,
      });
      onUpdated(updated);
      setSuccessMessage('Scheduling window saved.');
    } catch (err) {
      setBannerError(err instanceof ApiError ? err.message : 'Could not reach the server.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="settings-section">
      <h3>Scheduling window</h3>
      {bannerError && (
        <div className="banner-error" role="alert">
          {bannerError}
        </div>
      )}
      {successMessage && (
        <div className="banner-success" role="status">
          {successMessage}
        </div>
      )}

      <DayOfWeekRows
        legend="Active hours"
        hint="A day with no active hours is fully excluded from scheduling."
        renderControl={(day) => {
          const window = activeHours[day];
          const mode = activeHoursMode(window);
          return (
            <>
              <select
                aria-label={`${DAY_LABELS[day]} active hours`}
                value={mode}
                onChange={(event) => setActiveHoursDay(day, event.target.value as ActiveHoursMode)}
              >
                <option value="excluded">Excluded</option>
                <option value="custom">Custom</option>
              </select>
              {mode === 'custom' && (
                <>
                  <input
                    type="time"
                    aria-label={`${DAY_LABELS[day]} start`}
                    value={window?.start ?? DEFAULT_WINDOW.start}
                    onChange={(event) =>
                      setActiveHoursDay(day, 'custom', { start: event.target.value, end: window?.end ?? DEFAULT_WINDOW.end })
                    }
                  />
                  <span>to</span>
                  <input
                    type="time"
                    aria-label={`${DAY_LABELS[day]} end`}
                    value={window?.end ?? DEFAULT_WINDOW.end}
                    onChange={(event) =>
                      setActiveHoursDay(day, 'custom', { start: window?.start ?? DEFAULT_WINDOW.start, end: event.target.value })
                    }
                  />
                </>
              )}
            </>
          );
        }}
      />

      <fieldset className="field">
        <legend>Blackout dates</legend>
        {blackoutDates.length === 0 && <p style={{ color: 'var(--color-text-muted)' }}>No blackout dates.</p>}
        {blackoutDates.map((blackout, index) => (
          <div
            key={`${blackout.start}-${blackout.end}-${index}`}
            style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-2)' }}
          >
            <span>
              {blackout.start} – {blackout.end}
              {blackout.label ? ` (${blackout.label})` : ''}
            </span>
            <button type="button" onClick={() => removeBlackoutDate(index)} aria-label={`Remove blackout date ${index + 1}`}>
              Remove
            </button>
          </div>
        ))}
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
          <div>
            <label htmlFor="blackout-start">Start</label>
            <input
              id="blackout-start"
              type="date"
              value={newBlackoutStart}
              onChange={(event) => setNewBlackoutStart(event.target.value)}
            />
          </div>
          <div>
            <label htmlFor="blackout-end">End</label>
            <input id="blackout-end" type="date" value={newBlackoutEnd} onChange={(event) => setNewBlackoutEnd(event.target.value)} />
          </div>
          <div>
            <label htmlFor="blackout-label">Label (optional)</label>
            <input
              id="blackout-label"
              type="text"
              value={newBlackoutLabel}
              onChange={(event) => setNewBlackoutLabel(event.target.value)}
            />
          </div>
          <button type="button" onClick={addBlackoutDate}>
            Add blackout date
          </button>
        </div>
        {blackoutError && <p className="field-error">{blackoutError}</p>}
      </fieldset>

      <DayOfWeekRows
        legend="Daily time budget"
        hint="Soft cap on total scheduled minutes per day (§6.2's last resort can still exceed it unless enforcement is strict)."
        renderControl={(day) => {
          const minutes = dailyBudget[day];
          const unlimited = minutes === null;
          return (
            <>
              <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)', marginBottom: 0 }}>
                <input
                  type="checkbox"
                  aria-label={`${DAY_LABELS[day]} unlimited budget`}
                  checked={unlimited}
                  onChange={(event) => setDailyBudgetDay(day, event.target.checked ? null : DEFAULT_BUDGET_MINUTES)}
                />
                Unlimited
              </label>
              {!unlimited && (
                <DurationInput
                  id={`daily-budget-${day}`}
                  label={`${DAY_LABELS[day]} daily time budget`}
                  initialMinutes={minutes ?? DEFAULT_BUDGET_MINUTES}
                  units={DAILY_BUDGET_UNITS}
                  onChange={(value) => setDailyBudgetDay(day, value)}
                />
              )}
            </>
          );
        }}
      />

      <div className="field">
        <label htmlFor="budget-enforcement">Budget enforcement</label>
        <select
          id="budget-enforcement"
          value={budgetEnforcement}
          onChange={(event) => setBudgetEnforcement(event.target.value as BudgetEnforcement)}
        >
          <option value="soft">Meet the deadline (soft budget - may exceed as a last resort)</option>
          <option value="strict">Respect the budget (strict cap - becomes unschedulable instead)</option>
        </select>
      </div>

      <button type="button" className="primary" disabled={saving} onClick={() => void handleSave()}>
        {saving ? 'Saving…' : 'Save scheduling window'}
      </button>
    </section>
  );
}
