"use client";

import type { VideoProject } from "@/lib/api";
import type { ProductionPhase } from "@/lib/studio";
import { GenerationTimer } from "./GenerationTimer";
import { PrimaryButton, SecondaryButton } from "./ui";

export function ProductionHeader({
  phase,
  productName,
  generating = false,
  project,
  action,
  secondary,
}: {
  phase: ProductionPhase;
  productName?: string;
  generating?: boolean;
  project?: VideoProject | null;
  action?: {
    label: string;
    onClick: () => void;
    disabled?: boolean;
    pending?: boolean;
    hint?: string;
  } | null;
  secondary?: { label: string; onClick: () => void } | null;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4 rounded-2xl border border-line bg-card px-4 py-4 md:px-5">
      <div className="min-w-0">
        <p className="text-[11px] font-extrabold uppercase tracking-[0.16em] text-primary">MiSa Studio</p>
        <h1 className="mt-1 font-serif text-2xl text-foreground md:text-3xl">
          {productName || "Create a product video"}
        </h1>
        <p className="mt-2 text-sm" aria-live="polite">
          <span className="font-medium text-foreground">{phase.label}{generating ? "…" : ""}</span>
          <span className="text-muted"> · {phase.mike}</span>
        </p>
        {generating && project ? (
          <GenerationTimer project={project} running size="sm" className="mt-2" />
        ) : null}
      </div>
      {action || secondary ? (
        <div className="flex flex-col items-stretch gap-2 sm:items-end">
          <div className="flex flex-wrap gap-2">
            {secondary ? (
              <SecondaryButton type="button" onClick={secondary.onClick}>
                {secondary.label}
              </SecondaryButton>
            ) : null}
            {action ? (
              <PrimaryButton type="button" disabled={action.disabled || action.pending} onClick={action.onClick}>
                {action.pending ? "Working…" : action.label}
              </PrimaryButton>
            ) : null}
          </div>
          {action?.hint ? <p className="max-w-xs text-right text-xs text-muted">{action.hint}</p> : null}
        </div>
      ) : null}
    </header>
  );
}
