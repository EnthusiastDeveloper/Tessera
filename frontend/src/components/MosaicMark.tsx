/** Tessera's mark: a 3x3 mosaic of tiles (a tessera is one mosaic tile), in the Timeline's
 * own colours - accent, flexible and fixed. Decorative: the visible "tessera" wordmark
 * next to it carries the name. */
export function MosaicMark({ size = 26 }: { size?: number }): JSX.Element {
  const tiles = [
    'var(--color-accent)',
    'var(--color-flexible-strong)',
    'var(--color-flexible)',
    'var(--color-flexible)',
    'var(--color-fixed)',
    'var(--color-flexible-strong)',
    'var(--color-flexible-strong)',
    'var(--color-flexible)',
    'var(--color-accent)',
  ];
  return (
    <svg width={size} height={size} viewBox="0 0 26 26" aria-hidden="true">
      {tiles.map((fill, i) => (
        <rect key={i} x={(i % 3) * 9} y={Math.floor(i / 3) * 9} width="8" height="8" rx="1.5" fill={fill} />
      ))}
    </svg>
  );
}
