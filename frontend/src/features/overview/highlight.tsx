/** Render a snippet with server-provided `[start, end)` highlight spans. */
export interface Piece {
  text: string;
  mark: boolean;
}

/** Split `text` into plain/marked pieces from (possibly unsorted/overlapping) spans. */
export function splitHighlights(text: string, spans: ReadonlyArray<readonly [number, number]>): Piece[] {
  const sorted = [...spans]
    .map(([s, e]) => [Math.max(0, s), Math.min(text.length, e)] as const)
    .filter(([s, e]) => e > s)
    .sort((a, b) => a[0] - b[0]);
  const pieces: Piece[] = [];
  let cursor = 0;
  for (const [s, e] of sorted) {
    const start = Math.max(s, cursor);
    if (start >= e) continue;
    if (start > cursor) pieces.push({ text: text.slice(cursor, start), mark: false });
    pieces.push({ text: text.slice(start, e), mark: true });
    cursor = e;
  }
  if (cursor < text.length) pieces.push({ text: text.slice(cursor), mark: false });
  return pieces;
}

export function Highlighted({ text, spans }: { text: string; spans: ReadonlyArray<readonly [number, number]> }) {
  return (
    <>
      {splitHighlights(text, spans).map((p, i) =>
        p.mark ? (
          <mark key={i} className="rounded-sm bg-warn-soft px-0.5 text-ink">
            {p.text}
          </mark>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </>
  );
}
