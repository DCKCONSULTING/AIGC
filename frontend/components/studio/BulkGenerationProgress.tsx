"use client";

import Link from "next/link";

import type { VideoProject } from "@/lib/api";
import { ACTIVE_STATUSES, historyKind } from "@/lib/studio";
import { GenerationTimer } from "./GenerationTimer";
import { GenerationProgress } from "./GenerationProgress";
import { PrimaryButton, SecondaryButton } from "./ui";

export function BulkGenerationProgress({
  projects,
  selectedId,
  pending,
  onSelect,
  onRetry,
  onCancel,
  onBack,
}: {
  projects: VideoProject[];
  selectedId?: number | null;
  pending: boolean;
  onSelect: (project: VideoProject) => void;
  onRetry: () => void;
  onCancel?: () => void;
  onBack: () => void;
}) {
  const selected = projects.find((item) => item.id === selectedId) || projects[0] || null;
  const running = projects.filter((item) => ACTIVE_STATUSES.has(item.status)).length;
  const failed = projects.filter((item) => item.status === "failed").length;
  const ready = projects.filter((item) => !ACTIVE_STATUSES.has(item.status) && item.status !== "failed").length;

  return (
    <div className="grid gap-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="font-serif text-3xl">Generating {projects.length} videos</h2>
          <p className="mt-2 text-sm text-muted">
            {running} running · {ready} ready · {failed} failed. All jobs started together.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {running && onCancel ? (
            <SecondaryButton type="button" disabled={pending} onClick={onCancel}>
              {pending ? "Stopping…" : "Stop all"}
            </SecondaryButton>
          ) : null}
          <Link href="/brand/videos" className="text-sm font-medium text-primary">
            Open in Videos
          </Link>
        </div>
      </div>
      <ul className="grid gap-3 md:grid-cols-2">
        {projects.map((item, index) => {
          const active = selected?.id === item.id;
          const generating = ACTIVE_STATUSES.has(item.status);
          const concept =
            (item.creative_directions || []).find((row) => row.id === item.selected_concept_id)?.title ||
            item.product_name ||
            `Video ${index + 1}`;
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onSelect(item)}
                className={`w-full rounded-2xl border px-4 py-3 text-left ${
                  active ? "border-gold bg-gold/10" : "border-line bg-background"
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="font-medium">{concept}</p>
                    <p className="mt-1 text-xs text-muted">
                      {item.duration_seconds}s · {item.speaker_gender || "presenter"} · {historyKind(item.status)}
                    </p>
                  </div>
                  <GenerationTimer project={item} running={generating} size="sm" />
                </div>
                {item.stage_label ? <p className="mt-2 text-xs text-muted">{item.stage_label}</p> : null}
                {item.error_message ? <p className="mt-2 text-xs text-[#b71958]">{item.error_message}</p> : null}
              </button>
            </li>
          );
        })}
      </ul>
      {selected ? (
        <GenerationProgress
          project={selected}
          pending={pending}
          onRetry={onRetry}
          onCancel={onCancel}
          onBack={onBack}
          onEditFailed={onBack}
        />
      ) : (
        <div className="flex flex-wrap gap-3">
          <PrimaryButton type="button" disabled={pending} onClick={onRetry}>
            Retry batch
          </PrimaryButton>
          <SecondaryButton type="button" onClick={onBack}>
            Back to concepts
          </SecondaryButton>
        </div>
      )}
    </div>
  );
}
