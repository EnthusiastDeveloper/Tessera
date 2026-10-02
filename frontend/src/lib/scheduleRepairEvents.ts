/** A settings save that may have started a schedule repair (design doc §6.10) tells the
 * app-wide overlay to look, without the settings screen knowing where the overlay lives. */
const EVENT = 'tessera:schedule-repair-check';

export function announcePossibleScheduleRepair(): void {
  window.dispatchEvent(new Event(EVENT));
}

export function onPossibleScheduleRepair(listener: () => void): () => void {
  window.addEventListener(EVENT, listener);
  return () => window.removeEventListener(EVENT, listener);
}
