import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { getScheduleRepair } from '../api/settings';
import { onPossibleScheduleRepair } from '../lib/scheduleRepairEvents';
import type { ScheduleRepair } from '../types/settings';

const POLL_MS = 300;

/** Design doc §6.10/§8.1 (Rev 11): while a background schedule repair runs, cover the
 * screen with "Fixing the calendar (n/total)…", updated as each task is handled, so it
 * never looks stuck; when it ends, say what happened. Checks once on load (a reload
 * mid-repair shows it again) and whenever a settings save announces one may have
 * started. A repair that finished before this page saw it running is only summarised if
 * it is newer than the last one this page knew about. */
export function ScheduleRepairOverlay(): JSX.Element | null {
  const [running, setRunning] = useState<ScheduleRepair | null>(null);
  const [summary, setSummary] = useState<ScheduleRepair | null>(null);
  const knownId = useRef<string | null | undefined>(undefined);
  const polling = useRef(false);
  const recheck = useRef(false);

  const check = useCallback(async (): Promise<void> => {
    if (polling.current) {
      // A save landed mid-check; look again once this one is done.
      recheck.current = true;
      return;
    }
    polling.current = true;
    try {
      let repair = await getScheduleRepair();
      const firstLook = knownId.current === undefined;
      let sawItRun = false;
      while (repair?.status === 'running') {
        sawItRun = true;
        setRunning(repair);
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        repair = await getScheduleRepair();
      }
      const finishedSinceLastLook = repair !== null && !firstLook && repair.id !== knownId.current;
      if (repair?.status === 'finished' && (sawItRun || finishedSinceLastLook)) setSummary(repair);
      knownId.current = repair?.id ?? null;
    } catch {
      // Progress display only - the repair itself runs server-side regardless.
    } finally {
      setRunning(null);
      polling.current = false;
    }
    if (recheck.current) {
      recheck.current = false;
      await check();
    }
  }, []);

  useEffect(() => {
    void check();
    return onPossibleScheduleRepair(() => void check());
  }, [check]);

  if (running) {
    return (
      <div className="overlay" role="dialog" aria-modal="true" aria-label="Fixing the calendar">
        <div className="overlay__card" role="status" aria-live="polite">
          <p>
            Fixing the calendar ({running.done}/{running.total})…
          </p>
          <progress value={running.done} max={Math.max(running.total, 1)} />
          <p style={{ color: 'var(--color-text-muted)', fontSize: 'var(--font-size-sm)' }}>
            Some scheduled tasks no longer fit your new scheduling window and are being placed again.
          </p>
        </div>
      </div>
    );
  }

  if (summary) {
    return (
      <div className="overlay" role="dialog" aria-modal="true" aria-label="Calendar fixed">
        <div className="overlay__card">
          <p>
            <strong>Calendar fixed.</strong> {summary.moved} task{summary.moved === 1 ? '' : 's'} moved to a new time.
          </p>
          {summary.unschedulable > 0 && (
            <p>
              {summary.unschedulable} task{summary.unschedulable === 1 ? '' : 's'} couldn’t be placed before{' '}
              {summary.unschedulable === 1 ? 'its' : 'their'} deadline -{' '}
              <Link to="/notifications" onClick={() => setSummary(null)}>
                see Notifications
              </Link>
              .
            </p>
          )}
          <button type="button" className="primary" onClick={() => setSummary(null)}>
            OK
          </button>
        </div>
      </div>
    );
  }

  return null;
}
