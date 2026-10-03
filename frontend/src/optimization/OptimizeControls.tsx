import { useEffect, useState } from 'react';
import { useOptimization } from './OptimizationContext';

function remaining(until: string | null): number {
  return until ? Math.max(0, Math.floor((new Date(until).getTime() - Date.now()) / 1000)) : 0;
}

/** Design doc §8.1: the Timeline's "Optimize Schedule" action, and - after one was applied -
 * the Undo button with its countdown, offered only while undoing is still safe and gone the
 * moment it is not (§6.11). */
export function OptimizeControls(): JSX.Element {
  const { latest, locked, start, undo, showResult } = useOptimization();
  const undoUntil =
    latest?.status === 'applied' && latest.undo_available ? latest.undo_until : null;
  const [seconds, setSeconds] = useState(() => remaining(undoUntil));

  useEffect(() => {
    setSeconds(remaining(undoUntil));
    if (undoUntil === null) return undefined;
    const timer = setInterval(() => setSeconds(remaining(undoUntil)), 1000);
    return () => clearInterval(timer);
  }, [undoUntil]);

  const canUndo = undoUntil !== null && seconds > 0;
  return (
    <div
      style={{
        display: 'flex',
        gap: 'var(--space-2)',
        alignItems: 'center',
        marginBottom: 'var(--space-3)',
      }}
    >
      <button type="button" disabled={locked} onClick={() => void start()}>
        Optimize Schedule
      </button>
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
