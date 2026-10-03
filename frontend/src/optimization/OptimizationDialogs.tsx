import type { ReactNode } from 'react';
import type { OptimizationSummary, ScheduleOptimization } from '../types/optimization';
import { useOptimization } from './OptimizationContext';
import type { Notice } from './OptimizationContext';

/** The user's own clock, short: "Tue 18:00, 7 Apr". */
function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    day: 'numeric',
    month: 'short',
  });
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** Design doc §6.11 "the summary - always": counts at a glance, then each change, with what
 * the user would lose first when this is a plan awaiting approval. */
export function SummaryBody({ summary }: { summary: OptimizationSummary }): JSX.Element {
  const { counts } = summary;
  return (
    <div>
      <p>
        {[
          counts.newly_scheduled > 0 &&
            `${plural(counts.newly_scheduled, 'task', 'tasks')} newly scheduled`,
          counts.moved > 0 && `${counts.moved} moved`,
          counts.lost > 0 && `${counts.lost} lost ${counts.lost === 1 ? 'its' : 'their'} place`,
          counts.over_budget > 0 && `${counts.over_budget} over budget`,
          `${counts.unchanged} left as they were`,
        ]
          .filter(Boolean)
          .join(', ')}
        .
      </p>
      {summary.lost.length > 0 && (
        <Section title="Would lose their place" tone="danger">
          {summary.lost.map((x) => (
            <li key={x.instance_id}>
              <strong>{x.name}</strong> - no free slot before its deadline
              {x.deadline ? ` (${when(x.deadline)})` : ''}; it was at {when(x.from)}
            </li>
          ))}
        </Section>
      )}
      {summary.over_budget.length > 0 && (
        <Section title="Over their day's time budget" tone="danger">
          {summary.over_budget.map((x) => (
            <li key={x.instance_id}>
              <strong>{x.name}</strong>
            </li>
          ))}
        </Section>
      )}
      {summary.newly_scheduled.length > 0 && (
        <Section title="Newly scheduled">
          {summary.newly_scheduled.map((x) => (
            <li key={x.instance_id}>
              <strong>{x.name}</strong> - {when(x.to)}
            </li>
          ))}
        </Section>
      )}
      {summary.moved.length > 0 && (
        <Section title="Moved">
          {summary.moved.map((x) => (
            <li key={x.instance_id}>
              <strong>{x.name}</strong> - {when(x.from)} → {when(x.to)}
            </li>
          ))}
        </Section>
      )}
    </div>
  );
}

function Section({
  title,
  tone,
  children,
}: {
  title: string;
  tone?: 'danger';
  children: ReactNode;
}): JSX.Element {
  return (
    <section style={{ marginBottom: 'var(--space-3)' }}>
      <h4 style={tone === 'danger' ? { color: 'var(--color-danger)' } : undefined}>{title}</h4>
      <ul>{children}</ul>
    </section>
  );
}

function Dialog({ label, children }: { label: string; children: ReactNode }): JSX.Element {
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label={label}>
      <div className="overlay__card" style={{ maxHeight: '85vh', overflowY: 'auto' }}>
        {children}
      </div>
    </div>
  );
}

function ApprovalDialog({ optimization }: { optimization: ScheduleOptimization }): JSX.Element {
  const { approve, decline } = useOptimization();
  return (
    <Dialog label="Optimize Schedule - approval needed">
      <h3>Optimize Schedule</h3>
      {optimization.plan_changed && (
        <p className="banner-warning">
          The schedule changed since you last looked, so this is a new plan.
        </p>
      )}
      <p>
        A better arrangement exists, but it would take something you have today. Nothing has changed
        yet.
        {optimization.valid_until && (
          <> This plan stays valid until {when(optimization.valid_until)}.</>
        )}
      </p>
      {optimization.summary && <SummaryBody summary={optimization.summary} />}
      <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
        <button type="button" onClick={() => void decline()}>
          Cancel
        </button>
        <button type="button" className="primary" onClick={() => void approve()}>
          Apply
        </button>
      </div>
    </Dialog>
  );
}

function ResultDialog({ optimization }: { optimization: ScheduleOptimization }): JSX.Element {
  const { closeNotice, undo } = useOptimization();
  let heading = 'Optimize Schedule';
  let body: ReactNode;
  if (optimization.status === 'applied' && optimization.summary) {
    heading = 'Schedule optimized';
    body = <SummaryBody summary={optimization.summary} />;
  } else if (optimization.status === 'nothing_to_do') {
    heading = 'No better arrangement';
    body = (
      <p>
        {optimization.reason === 'would_place_fewer'
          ? 'The only different arrangement would leave more tasks without a slot than today, so nothing was changed.'
          : 'Your schedule is already as good as it gets. Nothing was changed.'}
      </p>
    );
  } else if (optimization.status === 'failed') {
    heading = 'Could not finish';
    body = <p>{optimization.reason ?? 'Something went wrong.'} Nothing was changed.</p>;
  } else if (optimization.status === 'undone') {
    heading = 'Schedule restored';
    body = <p>Your tasks are back where they were before the optimization.</p>;
  } else {
    body = <p>Done.</p>;
  }
  return (
    <Dialog label={heading}>
      <h3>{heading}</h3>
      {body}
      <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
        {optimization.status === 'applied' && optimization.undo_available && (
          <button type="button" onClick={() => void undo()}>
            Undo
          </button>
        )}
        <button type="button" className="primary" onClick={closeNotice}>
          Close
        </button>
      </div>
    </Dialog>
  );
}

function ErrorDialog({ message }: { message: string }): JSX.Element {
  const { closeNotice } = useOptimization();
  return (
    <Dialog label="Optimize Schedule - problem">
      <h3>Optimize Schedule</h3>
      <p role="alert">{message}</p>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button type="button" className="primary" onClick={closeNotice}>
          Close
        </button>
      </div>
    </Dialog>
  );
}

/** Rendered once by the app shell: whichever dialog the user currently owes an answer to. */
export function OptimizationDialogs(): JSX.Element | null {
  const { notice } = useOptimization();
  const current: Notice | null = notice;
  if (current === null) return null;
  if (current.kind === 'approval') return <ApprovalDialog optimization={current.optimization} />;
  if (current.kind === 'result') return <ResultDialog optimization={current.optimization} />;
  return <ErrorDialog message={current.message} />;
}
