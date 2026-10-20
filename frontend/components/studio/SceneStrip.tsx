"use client";

import type { StudioScene } from "@/lib/api";
import { formatClock, sceneLabel, sceneShot } from "@/lib/director";

export function SceneStrip({
  scenes,
  selectedKey,
  onSelect,
  onRegenerate,
  pending = false,
}: {
  scenes: StudioScene[];
  selectedKey?: string | null;
  onSelect?: (scene: StudioScene) => void;
  onRegenerate?: (scene: StudioScene) => void;
  pending?: boolean;
}) {
  if (!scenes.length) return null;

  return (
    <section className="min-w-0">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium text-foreground">Scenes</h2>
        <p className="text-xs text-muted">{scenes.length} scene{scenes.length === 1 ? "" : "s"}</p>
      </div>
      <ol className="mt-3 flex gap-3 overflow-x-auto pb-2">
        {scenes.map((scene, index) => {
          const selected = selectedKey === scene.scene_key;
          const failed = scene.scene_status === "failed" || scene.scene_status === "qa_failed";
          const generating = scene.scene_status === "generating" || scene.scene_status === "regenerating";
          return (
            <li key={scene.id || scene.scene_key} className="w-[7.5rem] shrink-0">
              <button
                type="button"
                onClick={() => onSelect?.(scene)}
                aria-pressed={selected}
                aria-label={`Scene ${scene.order || index + 1}${scene.title ? `, ${scene.title}` : ""}, ${sceneLabel(scene.scene_status)}`}
                className={`w-full overflow-hidden rounded-xl border text-left ${
                  selected
                    ? "border-primary ring-2 ring-[var(--misa-cyan)]/30"
                    : failed
                      ? "border-[#ffd0e2]"
                      : "border-line"
                }`}
              >
                <div className="relative bg-[#090f28]">
                  {scene.image_url || scene.video_url ? (
                    scene.video_url ? (
                      <video src={scene.video_url} className="aspect-[9/16] w-full object-cover" muted playsInline />
                    ) : (
                      <img src={scene.image_url} alt="" className="aspect-[9/16] w-full object-cover" />
                    )
                  ) : (
                    <div className="flex aspect-[9/16] items-center justify-center text-[11px] text-white/70">
                      {String(scene.order || index + 1).padStart(2, "0")}
                    </div>
                  )}
                  <span className="absolute left-1.5 top-1.5 rounded bg-[#090f28]/80 px-1.5 py-0.5 text-[10px] font-medium text-white">
                    {String(scene.order || index + 1).padStart(2, "0")}
                  </span>
                </div>
                <div className="px-2 py-2">
                  <p className="truncate text-xs font-medium">{scene.title || `Scene ${index + 1}`}</p>
                  <p className="mt-0.5 truncate text-[10px] text-muted">
                    {sceneLabel(scene.scene_status)}
                    {scene.duration ? ` · ${scene.duration}s` : ""}
                    {scene.start_time != null ? ` · ${formatClock(scene.start_time)}` : ""}
                  </p>
                  {failed ? (
                    <p className="mt-1 line-clamp-2 text-[10px] text-[var(--error)]">
                      {scene.error || "Failed"}
                    </p>
                  ) : (
                    <p className="mt-1 line-clamp-2 text-[10px] text-muted">{sceneShot(scene)}</p>
                  )}
                </div>
              </button>
              {onRegenerate && (failed || !generating) ? (
                <button
                  type="button"
                  disabled={pending}
                  onClick={() => onRegenerate(scene)}
                  className="mt-1.5 w-full rounded-full border border-line px-2 py-1 text-[10px] hover:border-primary disabled:opacity-40"
                >
                  {failed ? "Retry scene" : `Regenerate Scene ${String(scene.order || index + 1).padStart(2, "0")}`}
                </button>
              ) : null}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
