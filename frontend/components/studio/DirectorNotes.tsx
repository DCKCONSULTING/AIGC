"use client";

import type { ProductionPhase } from "@/lib/studio";

export function DirectorNotes({
  phase,
  generating = false,
}: {
  phase: ProductionPhase;
  generating?: boolean;
}) {
  return (
    <aside className="min-w-0 rounded-2xl border border-line bg-card p-4">
      <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-primary">AI directors</p>
      <p className="mt-3 text-xs uppercase tracking-[0.14em] text-muted" aria-live="polite">
        {phase.label}
        {generating ? "…" : ""}
      </p>

      <article className="mt-4">
        <p className="text-sm font-medium text-foreground">Sara</p>
        <p className="text-[11px] text-muted">Creative director · story, script, mood</p>
        <p className="mt-2 text-sm leading-6">{phase.sara}</p>
      </article>

      <article className="mt-5 border-t border-line pt-4">
        <p className="text-sm font-medium text-foreground">Mike</p>
        <p className="text-[11px] text-muted">Production director · scenes, voice, delivery</p>
        <p className="mt-2 text-sm leading-6">{phase.mike}</p>
      </article>
    </aside>
  );
}
