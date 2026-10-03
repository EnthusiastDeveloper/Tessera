import { useEffect, useState } from 'react';
import { getOptimizationOpportunity } from '../api/scheduleOptimizations';
import type { OptimizationOpportunity } from '../types/optimization';
import { useOptimization } from './OptimizationContext';

function remaining(until: string | null): number {
  return until ? Math.max(0, Math.floor((new Date(until).getTime() - Date.now()) / 1000)) : 0;
}

/** What the button's hint says (design doc §6.11, §8.1). */
export function gainHint(opportunity: OptimizationOpportunity): string {
  const more = `${opportunity.gain} more ${opportunity.gain === 1 ? 'task' : 'tasks'} could be scheduled`;
  return opportunity.needs_approval ? `${more} - needs your approval` : more;
}

export const NOTHING_TO_IMPROVE = 'Nothing to improve right now';

/** Design doc §8.1: the Timeline's "Optimize Schedule" action, and - after one was applied -
 * the Undo button with its countdown, offered only while undoing is still safe and gone the
 * moment it is not (§6.11).
 *
 * The button says whether pressing it is worth it: when it would get more tasks scheduled it
 * stays enabled, carries a hint and a spinning rainbow border to catch the eye; when it would
 * gain nothing it is grayed out but still there (so the feature stays discoverable) and says
 * why. The answer is read-only and re-asked whenever the schedule may have changed; if it
 * cannot be had, the button is simply an ordinary enabled one. */
export function OptimizeControls(): JSX.Element {
  const { latest, loaded, locked, scheduleRevision, start, undo, showResult } = useOptimization();
  const [opportunity, setOpportunity] = useState<OptimizationOpportunity | null>(null);
  const undoUntil =
    latest?.status === 'applied' && latest.undo_available ? latest.undo_until : null;
  const [seconds, setSeconds] = useState(() => remaining(undoUntil));

  useEffect(() => {
    if (!loaded || locked) return undefined;
    let cancelled = false;
    getOptimizationOpportunity()
      .then((found) => {
        if (!cancelled) setOpportunity(found);
      })
      .catch(() => {
        if (!cancelled) setOpportunity(null);
      });
    return () => {
      cancelled = true;
    };
  }, [loaded, locked, scheduleRevision]);

  useEffect(() => {
    setSeconds(remaining(undoUntil));
    if (undoUntil === null) return undefined;
    const timer = setInterval(() => setSeconds(remaining(undoUntil)), 1000);
    return () => clearInterval(timer);
  }, [undoUntil]);

  const canUndo = undoUntil !== null && seconds > 0;
  const worthwhile = opportunity?.worthwhile === true;
  const nothingToGain = opportunity !== null && !opportunity.worthwhile;

  return (
    <div
      style={{
        display: 'flex',
        gap: 'var(--space-2)',
        alignItems: 'center',
        marginBottom: 'var(--space-3)',
      }}
    >
      <span title={nothingToGain ? NOTHING_TO_IMPROVE : undefined}>
        <button
          type="button"
          className={worthwhile ? 'optimize-button optimize-button--attention' : 'optimize-button'}
          disabled={locked || nothingToGain}
          onClick={() => void start()}
        >
          Optimize Schedule
        </button>
      </span>
      {worthwhile && opportunity && (
        <span className="optimize-hint" role="status">
          {gainHint(opportunity)}
        </span>
      )}
      {nothingToGain && !locked && (
        <span className="optimize-hint optimize-hint--muted">{NOTHING_TO_IMPROVE}</span>
      )}
      {canUndo && (
        <>
          <button type="button" onClick={() => void undo()}>
            Undo optimization ({Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')})
          </button>
          <button type="button" onClick={showResult}>
            What changed
          </button>
        </>
      )}
    </div>
  );
}
