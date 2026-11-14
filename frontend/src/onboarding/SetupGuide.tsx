import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import { ApiError, toApiError } from '../api/client';
import { getSettings, updateSettings } from '../api/settings';
import { MosaicMark } from '../components/MosaicMark';
import { ScheduleRepairOverlay } from '../components/ScheduleRepairOverlay';
import { announcePossibleScheduleRepair } from '../lib/scheduleRepairEvents';
import type { UserSettings } from '../types/settings';
import { BudgetStep, DoneStep, HoursStep, TimezoneStep, WeekStep, type StepProps } from './GuideSteps';

const STEPS: ReadonlyArray<(props: StepProps) => JSX.Element> = [TimezoneStep, WeekStep, HoursStep, BudgetStep];
const DONE = STEPS.length;

// The step reached, per browser, so leaving mid-way picks up there (design doc 8.1 screen 0a).
// A convenience only: storage can be unavailable, and then the guide starts from the top.
const STEP_KEY = 'tessera.setupGuide.step';

function readSavedStep(): number {
  try {
    const saved = Number(window.localStorage.getItem(STEP_KEY));
    return Number.isInteger(saved) && saved >= 0 && saved < DONE ? saved : 0;
  } catch {
    return 0;
  }
}

function rememberStep(step: number | null): void {
  try {
    if (step === null) window.localStorage.removeItem(STEP_KEY);
    else window.localStorage.setItem(STEP_KEY, String(step));
  } catch {
    // Not remembering the step is fine.
  }
}

// A save that touches these may start a schedule repair (design doc 6.10).
const PLACEMENT_FIELDS: ReadonlyArray<keyof UserSettings> = ['active_hours', 'daily_time_budget_minutes', 'budget_enforcement'];

export interface SetupGuideRouteState {
  /** Settings' "Run the setup guide again": start from the first step. */
  restart?: boolean;
}

/** The first-run setup guide (design doc 8.1 screen 0a, Rev 16): a few prefilled,
 * skippable steps over the settings that shape a schedule, ending with where to go next.
 * Reaching the end or "Skip setup" sets `onboarding_completed` (3.7), which stops
 * `OnboardingGate` sending the user here. */
export function SetupGuide(): JSX.Element {
  const navigate = useNavigate();
  const location = useLocation();
  const restart = (location.state as SetupGuideRouteState | null)?.restart === true;
  const [step, setStep] = useState(() => (restart ? 0 : readSavedStep()));
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((loaded) => {
        if (!cancelled) setSettings(loaded);
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(toApiError(err).message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const goTo = (next: number): void => {
    setError(null);
    setStep(next);
    rememberStep(next >= DONE ? null : next);
  };

  /** Saves the step's answers (if any) and moves on; arriving at the end also records
   * that the guide is done. */
  const saveAndGo = async (patch: Partial<UserSettings>, next: number): Promise<void> => {
    const body: Partial<UserSettings> = next >= DONE ? { ...patch, onboarding_completed: true } : patch;
    if (Object.keys(body).length === 0) {
      goTo(next);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      setSettings(await updateSettings(body));
      if (PLACEMENT_FIELDS.some((field) => field in body)) announcePossibleScheduleRepair();
      goTo(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reach the server.');
    } finally {
      setSaving(false);
    }
  };

  const skipSetup = async (): Promise<void> => {
    setSaving(true);
    setError(null);
    try {
      await updateSettings({ onboarding_completed: true });
      rememberStep(null);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reach the server.');
      setSaving(false);
    }
  };

  const Step = step < DONE ? STEPS[step] : null;

  return (
    <div className="min-h-screen bg-bg">
      <header className="flex min-h-18 items-center gap-2.5 px-4 py-4 sm:px-8">
        <MosaicMark />
        <span className="font-display text-lg font-bold tracking-tight">tessera</span>
        <div className="flex-1" />
        {step < DONE && settings && (
          <button type="button" onClick={() => void skipSetup()} disabled={saving}>
            Skip setup
          </button>
        )}
      </header>
      <main className="mx-auto w-full max-w-xl px-4 pb-12 pt-4 sm:pt-10">
        {step < DONE && (
          <div className="mb-6 flex items-center gap-3">
            <ol className="m-0 flex list-none gap-1.5 p-0" aria-hidden="true">
              {STEPS.map((_, index) => (
                <li
                  key={index}
                  className={`size-3 rounded-sm ${index <= step ? 'bg-accent' : 'bg-surface-raised'}`}
                />
              ))}
            </ol>
            <span className="text-sm text-text-muted">
              Step {step + 1} of {DONE}
            </span>
          </div>
        )}
        <div className="rounded-lg border border-border bg-surface p-6 shadow-card sm:p-8">
          {error && (
            <div className="banner-error" role="alert">
              {error}
            </div>
          )}
          {loadError && (
            <div className="banner-error" role="alert">
              {loadError}
            </div>
          )}
          {!settings && !loadError && <p className="text-text-muted">Loading…</p>}
          {settings && Step && (
            <Step
              key={step}
              settings={settings}
              saving={saving}
              onContinue={(patch) => void saveAndGo(patch, step + 1)}
              onSkip={() => void saveAndGo({}, step + 1)}
              onBack={step > 0 ? () => goTo(step - 1) : undefined}
            />
          )}
          {settings && !Step && <DoneStep onNavigate={(to) => navigate(to, { replace: true })} />}
        </div>
      </main>
      <ScheduleRepairOverlay />
    </div>
  );
}
