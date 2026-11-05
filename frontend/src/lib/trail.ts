/**
 * Where the user came from. Every screen the app shows is remembered under its browser
 * history position (react-router's `history.state.idx`), with a short label. The context
 * line reads the entry one position back and offers "← <label>" — a visible browser Back —
 * whichever link brought the user here (evidence chip, guide bar, tab, search hit …).
 *
 * Stored in sessionStorage so a reload keeps it; storage failures only hide the back link.
 */

export interface TrailEntry {
  /** Identity of the screen: tab + sub-view + experiment (two visits of one screen are one). */
  screen: string;
  /** Short label, e.g. "Records · 실패 아카이브", "Research AI · #024". */
  label: string;
}

const KEY = "biopilot.trail";
/** Positions kept around the current one (older ones are dropped). */
const KEEP = 50;

function load(): Record<string, TrailEntry> {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Record<string, TrailEntry>) : {};
  } catch {
    return {};
  }
}

function save(map: Record<string, TrailEntry>): void {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify(map));
  } catch {
    /* private mode / quota: the back link is a convenience only */
  }
}

/** Current history position (0 when the router has not stamped one yet). */
export function historyIndex(): number {
  const state = window.history.state as { idx?: unknown } | null;
  return typeof state?.idx === "number" ? state.idx : 0;
}

/** Remember what is shown at history position `idx`. */
export function recordVisit(idx: number, entry: TrailEntry): void {
  const map = load();
  const prev = map[idx];
  if (prev && prev.screen === entry.screen && prev.label === entry.label) return;
  map[idx] = entry;
  for (const k of Object.keys(map)) if (Math.abs(Number(k) - idx) > KEEP) delete map[k];
  save(map);
}

/** The screen one history step back, if it is a different screen than `screen`. */
export function previousVisit(idx: number, screen: string): TrailEntry | null {
  if (idx <= 0) return null;
  const prev = load()[idx - 1];
  return prev && prev.screen !== screen ? prev : null;
}
