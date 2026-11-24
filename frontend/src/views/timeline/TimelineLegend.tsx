/** Every kind of block the Timeline draws, in the order a user meets them (design doc 8.1
 * screen 2, Rev 19). Each swatch reuses the colours and pattern of the block it names
 * (`.legend-swatch--*` in `src/index.css` mirrors the `.fc-event-*` rules), and the label
 * carries the meaning - colour is never the only signal. */
const KINDS: { key: string; label: string; title: string }[] = [
  { key: 'fixed', label: 'Fixed task', title: 'Keeps the time you gave it' },
  { key: 'flexible', label: 'Flexible task', title: 'Tessera picked this time for it' },
  { key: 'waiting', label: 'Waiting', title: 'A fixed task waiting on another task to be done' },
  { key: 'virtual', label: 'Upcoming repeat', title: 'A future occurrence of a repeating task, not created yet' },
  { key: 'external', label: 'Other calendar', title: 'An event from a connected calendar - read only' },
  { key: 'blackout', label: 'Blackout day', title: 'Nothing is scheduled on this day' },
];

export function TimelineLegend(): JSX.Element {
  return (
    <ul className="timeline-legend" aria-label="Legend">
      {KINDS.map((kind) => (
        <li key={kind.key} title={kind.title}>
          <span className={`legend-swatch legend-swatch--${kind.key}`} aria-hidden="true" />
          {kind.label}
        </li>
      ))}
    </ul>
  );
}
