import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import type { ReactNode } from 'react';
import { ApiError, toApiError } from '../api/client';
import {
  approveOptimization,
  declineOptimization,
  getLatestOptimization,
  startOptimization,
  undoOptimization,
} from '../api/scheduleOptimizations';
import type { ScheduleOptimization } from '../types/optimization';

const POLL_MS = 500;
const HINT_MS = 5000;

/** What a locked control says when the user tries it (design doc §6.11, §8.1). */
export const LOCK_HINT = 'Your schedule is being optimized. Editing is paused until it finishes.';

/** Something the user is shown once as a dialog, after an action or on reload (an unanswered
 * approval). Closing it does not undo anything. */
export type Notice =
  | { kind: 'approval'; optimization: ScheduleOptimization }
  | { kind: 'result'; optimization: ScheduleOptimization }
  | { kind: 'error'; message: string };

interface OptimizationContextValue {
  latest: ScheduleOptimization | null;
  /** The latest state has been read at least once - until then `locked` may be a false "no". */
  loaded: boolean;
  /** An optimization is running: the schedule is read-only (design doc §6.11). */
  locked: boolean;
  /** It has run longer than the server's "taking longer than expected" threshold. */
  slow: boolean;
  /** Bumps whenever the schedule changed under the user (applied or undone), so views reload. */
  scheduleRevision: number;
  notice: Notice | null;
  hintVisible: boolean;
  start: () => Promise<void>;
  approve: () => Promise<void>;
  decline: () => Promise<void>;
  undo: () => Promise<void>;
  closeNotice: () => void;
  showResult: () => void;
  /** For a locked control: tell the user why nothing happened. */
  showLockHint: () => void;
}

const noop = async (): Promise<void> => undefined;

/** Without a provider (a page rendered on its own, in a test) nothing is ever locked. */
const DEFAULT_VALUE: OptimizationContextValue = {
  latest: null,
  loaded: true,
  locked: false,
  slow: false,
  scheduleRevision: 0,
  notice: null,
  hintVisible: false,
  start: noop,
  approve: noop,
  decline: noop,
  undo: noop,
  closeNotice: () => undefined,
  showResult: () => undefined,
  showLockHint: () => undefined,
};

const OptimizationContext = createContext<OptimizationContextValue>(DEFAULT_VALUE);

export function useOptimization(): OptimizationContextValue {
  return useContext(OptimizationContext);
}

/** Owns "Optimize Schedule" for the signed-in app (design doc §6.11, §8.1): the latest
 * operation, polled while it runs; the read-only lock that follows from it; and the dialogs'
 * state. Checks once on load, so a reload mid-run shows the lock again and an unanswered
 * approval comes back. */
export function OptimizationProvider({ children }: { children: ReactNode }): JSX.Element {
  const [latest, setLatest] = useState<ScheduleOptimization | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [scheduleRevision, setScheduleRevision] = useState(0);
  const [slow, setSlow] = useState(false);
  const [hintVisible, setHintVisible] = useState(false);
  const hintTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const watching = useRef<string | null>(null);

  const absorb = useCallback((next: ScheduleOptimization | null, announce: boolean): void => {
    setLatest(next);
    if (next === null) return;
    if (next.status === 'awaiting_approval') {
      setNotice({ kind: 'approval', optimization: next });
    } else if (announce) {
      if (next.status === 'applied') setScheduleRevision((n) => n + 1);
      if (next.status === 'undone') setScheduleRevision((n) => n + 1);
      if (['applied', 'nothing_to_do', 'failed', 'undone'].includes(next.status)) {
        setNotice({ kind: 'result', optimization: next });
      }
    }
  }, []);

  // Poll while one runs. Whatever it turns into is announced exactly once.
  const watch = useCallback(
    async (id: string): Promise<void> => {
      if (watching.current === id) return;
      watching.current = id;
      try {
        for (;;) {
          await new Promise((resolve) => setTimeout(resolve, POLL_MS));
          const next = await getLatestOptimization();
          if (next === null || next.id !== id || next.status !== 'running') {
            absorb(next, true);
            return;
          }
          setLatest(next);
        }
      } catch {
        // Progress display only; the run itself continues server-side regardless.
      } finally {
        watching.current = null;
      }
    },
    [absorb]
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const first = await getLatestOptimization();
        if (cancelled) return;
        absorb(first, false);
        if (first?.status === 'running') void watch(first.id);
      } catch {
        // No optimization state to show; the rest of the app works without it.
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [absorb, watch]);

  // "Taking longer than expected" after the server's configured threshold.
  const runningId = latest?.status === 'running' ? latest.id : null;
  const slowAfterMs = (latest?.slow_after_seconds ?? 0) * 1000;
  const requestedAt = latest?.requested_at;
  useEffect(() => {
    setSlow(false);
    if (runningId === null || requestedAt === undefined) return undefined;
    const remaining = new Date(requestedAt).getTime() + slowAfterMs - Date.now();
    if (remaining <= 0) {
      setSlow(true);
      return undefined;
    }
    const timer = setTimeout(() => setSlow(true), remaining);
    return () => clearTimeout(timer);
  }, [runningId, requestedAt, slowAfterMs]);

  const run = useCallback(
    async (action: () => Promise<ScheduleOptimization>): Promise<void> => {
      try {
        const next = await action();
        setNotice(null);
        setLatest(next);
        if (next.status === 'running') void watch(next.id);
        else absorb(next, true);
      } catch (err) {
        const error = toApiError(
          err,
          new ApiError(0, 'network_error', 'Could not reach the server.')
        );
        if (error.code === 'undo_unavailable' || error.code === 'optimization_expired') {
          setNotice({ kind: 'error', message: 'This can no longer be undone.' });
          try {
            absorb(await getLatestOptimization(), false);
          } catch {
            // The button disappears on the next successful refresh.
          }
        } else {
          setNotice({ kind: 'error', message: error.message });
        }
      }
    },
    [absorb, watch]
  );

  const start = useCallback(() => run(startOptimization), [run]);
  const approve = useCallback(async () => {
    if (latest) await run(() => approveOptimization(latest.id));
  }, [latest, run]);
  const decline = useCallback(async () => {
    if (latest) await run(() => declineOptimization(latest.id));
    setNotice(null);
  }, [latest, run]);
  const undo = useCallback(async () => {
    if (latest) await run(() => undoOptimization(latest.id));
  }, [latest, run]);

  const showLockHint = useCallback(() => {
    setHintVisible(true);
    if (hintTimer.current) clearTimeout(hintTimer.current);
    hintTimer.current = setTimeout(() => setHintVisible(false), HINT_MS);
  }, []);
  useEffect(
    () => () => {
      if (hintTimer.current) clearTimeout(hintTimer.current);
    },
    []
  );

  const value = useMemo<OptimizationContextValue>(
    () => ({
      latest,
      loaded,
      locked: latest?.status === 'running',
      slow,
      scheduleRevision,
      notice,
      hintVisible,
      start,
      approve,
      decline,
      undo,
      closeNotice: () => setNotice(null),
      showResult: () => {
        if (latest) setNotice({ kind: 'result', optimization: latest });
      },
      showLockHint,
    }),
    [
      latest,
      loaded,
      slow,
      scheduleRevision,
      notice,
      hintVisible,
      start,
      approve,
      decline,
      undo,
      showLockHint,
    ]
  );

  return <OptimizationContext.Provider value={value}>{children}</OptimizationContext.Provider>;
}
