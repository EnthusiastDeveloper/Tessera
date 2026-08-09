export function ComingSoon({ title, note }: { title: string; note: string }): JSX.Element {
  return (
    <div>
      <h2>{title}</h2>
      <p style={{ color: 'var(--color-text-muted)' }}>{note}</p>
    </div>
  );
}
