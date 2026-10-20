"use client";

import Link from "next/link";

import type { BulkGeneration } from "@/lib/api";
import { bulkProgress, itemStatusLabel, reviewHref } from "@/lib/bulk-studio";
import { GenerationTimer } from "../GenerationTimer";
import { PrimaryButton, SecondaryButton } from "../ui";

export function BulkProgress({
  batch,
  pending,
  onRetry,
  onCancel,
  onBack,
}: {
  batch: BulkGeneration;
  pending: boolean;
  onRetry: () => void;
  onCancel: () => void;
  onBack: () => void;
}) {
  const progress = bulkProgress(batch);
  const busy = batch.status === "queued" || batch.status === "generating";

  return (
    <div className="grid gap-6">
      <div>
        <h2 className="font-serif text-3xl">{batch.title || "Bulk Studio"}</h2>
        <p className="mt-2 text-sm text-muted">
          {progress.completed} / {progress.total} completed
          {progress.failed ? ` · ${progress.failed} failed` : ""}
          {progress.generating ? ` · ${progress.generating} in progress` : ""}
        </p>
        <GenerationTimer
          timerKey={`bulk-${batch.id}`}
          startedAt={batch.started_at || batch.created_at}
          running={busy}
          size="lg"
          className="mt-4"
        />
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#eef3f8]" aria-hidden>
          <div className="h-full bg-[var(--misa-cyan)]" style={{ width: `${progress.percent}%` }} />
        </div>
      </div>
      <ol className="grid gap-3">
        {batch.items.map((item) => {
          const href = reviewHref(item.video_project?.id);
          return (
            <li key={item.id} className="flex flex-wrap items-center gap-4 rounded-2xl border border-line bg-card px-4 py-3">
              {item.video_project?.poster_url ? (
                <img
                  src={item.video_project.poster_url}
                  alt=""
                  className="h-16 w-12 rounded-lg object-cover"
                />
              ) : item.video_project?.preview_url ? (
                <video className="h-16 w-12 rounded-lg object-cover" src={item.video_project.preview_url} muted />
              ) : (
                <span className="grid h-16 w-12 place-items-center rounded-lg bg-[#f0f3f7] text-xs text-muted">
                  {String(item.sequence).padStart(2, "0")}
                </span>
              )}
              <div className="min-w-0 flex-1">
                <p className="font-medium">{item.title || `Video ${String(item.sequence).padStart(2, "0")}`}</p>
                <p className={`mt-1 text-xs ${item.status === "failed" ? "text-[#b71958]" : "text-muted"}`}>
                  {itemStatusLabel(item)}
                </p>
                {item.video_project && (item.status === "queued" || item.status === "generating") ? (
                  <GenerationTimer project={item.video_project} running size="sm" className="mt-1" />
                ) : null}
              </div>
              {href ? (
                <Link href={href} className="text-sm font-medium text-primary">
                  Open in Studio
                </Link>
              ) : null}
            </li>
          );
        })}
      </ol>
      <div className="flex flex-wrap gap-3">
        {batch.failed_count ? (
          <PrimaryButton type="button" disabled={pending} onClick={onRetry}>
            Retry failed
          </PrimaryButton>
        ) : null}
        {busy ? (
          <SecondaryButton type="button" disabled={pending} onClick={onCancel}>
            {pending ? "Stopping…" : "Stop all"}
          </SecondaryButton>
        ) : (
          <SecondaryButton type="button" onClick={onBack}>
            New batch
          </SecondaryButton>
        )}
        <Link href="/brand/videos" className="self-center text-sm font-medium text-primary">
          Open in Videos
        </Link>
      </div>
    </div>
  );
}
