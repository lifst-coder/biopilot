import type { ReactNode } from "react";
import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";

/**
 * A technical term with its one-line explanation as a tooltip (dotted underline).
 * The visible text is unchanged, so labels stay searchable/testable as before.
 */
export function Term({ k, children }: { k: GlossaryKey; children: ReactNode }) {
  return (
    <abbr title={GLOSSARY[k]} className="cursor-help underline decoration-ink-faint decoration-dotted underline-offset-2">
      {children}
    </abbr>
  );
}
