import { LOCK_HINT, useOptimization } from './OptimizationContext';

/** While an optimization runs the schedule is read-only (design doc §6.11): this says so, and
 * says more when it is slow. Also the home of the hint a locked control shows when clicked. */
export function OptimizingBanner(): JSX.Element | null {
  const { locked, slow, hintVisible } = useOptimization();
  if (!locked && !hintVisible) return null;
  return (
    <div className="banner-warning" role="status" aria-live="polite">
      {locked ? (
        <>
          <strong>Optimizing your schedule…</strong> Editing is paused until it finishes.
          {slow && ' This is taking longer than expected.'}
        </>
      ) : (
        LOCK_HINT
      )}
      {locked && hintVisible && <div>{LOCK_HINT}</div>}
    </div>
  );
}
