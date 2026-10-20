"use client";

import Link from "next/link";

import type { VideoProject } from "@/lib/api";
import {
  PROGRESS_STEPS,
  generationFailureView,
  progressStepIndex,
  productionPhase,
  sceneRetryBlocked,
} from "@/lib/studio";
import { GenerationTimer } from "./GenerationTimer";
import { VideoStage } from "./VideoStage";
import { PrimaryButton, SecondaryButton } from "./ui";

export function GenerationProgress({
  project,
  pending,
  onRetry,
  onBack,
  onCancel,
  onEditFailed,
}: {
  project: VideoProject;
  pending: boolean;
  onRetry: () => void;
  onBack: () => void;
  onCancel?: () => void;
  onEditFailed?: () => void;
}) {
  const current = progressStepIndex(project.status || "queued");
  const scenes = project.scenes || [];
  const failed = scenes.filter(
    (scene) => scene.scene_status === "failed" || scene.scene_status === "qa_failed" || scene.generation_status === "failed",
  );
  const failedRun = project.status === "failed";
  const retryBlocked = sceneRetryBlocked(failed);
  const phase = productionPhase(project);
  const generating = !failedRun;

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
      <VideoStage project={project} generating={generating} />
      <div>
        <h2 className="font-serif text-3xl text-foreground">
          {failedRun ? "Generation failed" : `${phase.label}${generating ? "…" : ""}`}
        </h2>
        {generating ? (
          <GenerationTimer project={project} running className="mt-4" size="lg" />
        ) : failedRun ? (
          <GenerationTimer project={project} running={false} className="mt-4" size="md" />
        ) : null}
        <p className="mt-2 text-sm text-muted">
          {project.stage_label || phase.mike}
          {project.updated_at
            ? ` Last update ${new Date(project.updated_at).toLocaleTimeString("en-MY", { hour: "2-digit", minute: "2-digit" })}.`
            : ""}
        </p>
        {project.preview_url ? (
          <p className="mt-3 text-sm">
            The file is already saved in Videos while this run continues.{" "}
            <Link href={`/brand/videos?id=${project.id}`} className="text-[var(--success)] underline-offset-2 hover:underline">
              Open in Projects
            </Link>
          </p>
        ) : generating ? (
          <p className="mt-3 text-sm text-muted">It will appear in Projects as soon as the file is ready.</p>
        ) : null}

        <ol className="mt-6 grid gap-3">
          {PROGRESS_STEPS.map((item, index) => {
            const done = index < current;
            const active = index === current && generating;
            return (
              <li key={item.id} className="flex items-center gap-3 text-sm">
                <span
                  className={`inline-flex h-7 w-7 items-center justify-center rounded-full text-xs ${
                    done
                      ? "bg-[#e7fbff] text-[var(--success)]"
                      : active
                        ? "bg-primary text-white"
                        : "bg-black/5 text-muted"
                  }`}
                >
                  {done ? "✓" : active ? "●" : "○"}
                </span>
                <span className={active ? "font-medium" : done ? "" : "text-muted"}>{item.label}</span>
              </li>
            );
          })}
        </ol>

        {(() => {
          const metrics = project.generation_metrics || {};
          const doneScenes = (project.scenes || []).filter(
            (scene) => scene.generation_status === "completed" || scene.scene_status === "generated" || scene.video_url,
          ).length;
          const totalScenes = (project.scenes || []).length;
          return (
            <div className="mt-6 grid gap-1 text-sm text-muted">
              {totalScenes ? (
                <p>
                  Scenes: {doneScenes} / {totalScenes}
                  {metrics.scene_concurrency ? ` · concurrency ${metrics.scene_concurrency}` : ""}
                </p>
              ) : null}
              {metrics.scene_generation_parallel_ms ? (
                <p>Scene generation wall: {Math.round(metrics.scene_generation_parallel_ms / 1000)}s</p>
              ) : null}
            </div>
          );
        })()}

        {failed.length ? (
          <div className="mt-6 grid gap-3">
            {failed.map((scene) => {
              const failure = generationFailureView(scene);
              return (
                <div key={scene.scene_key} className="rounded-2xl border border-[#ffd0e2] bg-[#fff0f6] p-4 text-sm text-foreground">
                  <p className="font-medium">{failure.summary || failure.title}</p>
                  <p className="mt-2">Provider: {failure.provider === "omni" ? "Omni" : failure.provider}</p>
                  {failure.requestId ? <p className="mt-1">Interaction ID: {failure.requestId}</p> : null}
                  {failure.httpStatus ? <p className="mt-1">HTTP status: {failure.httpStatus}</p> : null}
                  <p className="mt-1">Error code: {failure.code}</p>
                  <p className="mt-1">Provider message: {failure.message}</p>
                  {!failure.retryable ? (
                    <p className="mt-3">This scene cannot be retried until the configuration is fixed.</p>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : null}

        {generating && onCancel ? (
          <div className="mt-6 flex flex-wrap gap-3">
            <SecondaryButton type="button" disabled={pending} onClick={onCancel}>
              {pending ? "Stopping…" : "Stop generation"}
            </SecondaryButton>
          </div>
        ) : null}

        {failedRun ? (
          <div className="mt-6 flex flex-wrap gap-3">
            {retryBlocked ? null : (
              <PrimaryButton type="button" disabled={pending} onClick={onRetry}>
                {pending ? "Starting…" : "Retry"}
              </PrimaryButton>
            )}
            <SecondaryButton type="button" onClick={onEditFailed || onBack}>
              Edit storyboard
            </SecondaryButton>
            <SecondaryButton type="button" onClick={onBack}>
              Back to storyboard
            </SecondaryButton>
            <Link
              href={`/brand/studio?project=${project.id}&step=compose`}
              className="inline-flex h-11 items-center rounded-full border border-line px-5 text-sm"
            >
              Back to Brief
            </Link>
          </div>
        ) : null}
      </div>
    </div>
  );
}
