"use client";

import type { VideoProject } from "@/lib/api";
import { ACTIVE_STATUSES, productionBarWidth, productionPhase } from "@/lib/studio";
import { GenerationTimer } from "./GenerationTimer";

export function VideoStage({
  project,
  generating = false,
}: {
  project?: VideoProject | null;
  generating?: boolean;
}) {
  const src = project?.preview_url || project?.final_url || project?.export_url || "";
  const failed = project?.status === "failed";
  const phase = productionPhase(project);
  const scenes = project?.scenes || [];
  const current = scenes.find((scene) =>
    ["generating", "regenerating"].includes(scene.scene_status || ""),
  );
  const readyCount = scenes.filter((scene) =>
    ["generated", "ready", "approved"].includes(scene.scene_status || ""),
  ).length;
  const width = productionBarWidth(project?.status || "", project?.progress);
  const showBar = generating || ACTIVE_STATUSES.has(project?.status || "");

  return (
    <div className="mx-auto w-full max-w-[18rem]">
      <div className="relative overflow-hidden rounded-2xl bg-[#090f28]">
        {src && !failed ? (
          <video
            className="aspect-[9/16] w-full object-cover"
            src={src}
            controls
            playsInline
            preload="metadata"
            aria-label="Video preview"
          />
        ) : (
          <div
            className="flex aspect-[9/16] flex-col items-center justify-center px-5 text-center text-white"
            role="status"
            aria-live="polite"
          >
            {failed ? (
              <>
                <p className="text-sm font-medium">Video generation failed</p>
                <p className="mt-2 text-xs text-white/70">
                  {project?.error_message || "The video service did not complete this request."}
                </p>
              </>
            ) : generating ? (
              <>
                <p className="text-sm font-medium">{phase.label}</p>
                {scenes.length ? (
                  <p className="mt-2 text-xs text-white/75">
                    Scene {Math.min(readyCount + 1, scenes.length)} of {scenes.length}
                    {current?.title ? ` · ${current.title}` : ""}
                  </p>
                ) : null}
                <p className="mt-2 text-xs text-white/60">
                  {project?.stage_label || "Preparing motion and voice"}
                </p>
                <GenerationTimer
                  project={project}
                  running
                  size="sm"
                  className="mt-4 rounded-full bg-white/10 px-3 py-1 text-white"
                />
              </>
            ) : (
              <p className="text-sm text-white/70">Preview will appear here</p>
            )}
          </div>
        )}
        {src && generating ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-[#090f28]/80 px-3 py-2 text-[11px] text-white">
            <p className="font-medium">{phase.label}</p>
            {scenes.length ? (
              <p className="mt-0.5 text-white/70">
                Scene {Math.min(readyCount + 1, scenes.length)} of {scenes.length}
              </p>
            ) : null}
            <GenerationTimer project={project} running size="sm" className="mt-1 text-white" />
          </div>
        ) : null}
      </div>
      {showBar ? (
        <div
          className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#dfe7f3]"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={typeof project?.progress === "number" && project.progress > 0 ? project.progress : undefined}
          aria-label={phase.label}
        >
          <div
            className="h-full bg-primary transition-all"
            style={{ width: `${width}%` }}
          />
        </div>
      ) : null}
    </div>
  );
}
