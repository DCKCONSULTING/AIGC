"use client";

import type { StudioScene } from "@/lib/api";
import { formatClock, sceneCaption, sceneLabel, sceneShot, sceneStatusIcon, sceneVoice } from "@/lib/director";
import { DURATION_OPTIONS } from "@/lib/studio";
import { LockControls } from "./LockControls";
import { PrimaryButton, SecondaryButton } from "./ui";

export function StoryboardTimeline({
  scenes,
  duration,
  pending,
  selectedKey,
  onSelect,
  onDuration,
  onEdit,
  onDuplicate,
  onDelete,
  onMove,
  onLock,
  onRegenerate,
  onApprove,
  onGenerate,
  characterName,
}: {
  scenes: StudioScene[];
  duration: number;
  pending: boolean;
  selectedKey?: string | null;
  onSelect?: (scene: StudioScene) => void;
  onDuration: (value: number) => void;
  onEdit: (scene: StudioScene) => void;
  onDuplicate: (scene: StudioScene) => void;
  onDelete: (scene: StudioScene) => void;
  onMove: (scene: StudioScene, direction: -1 | 1) => void;
  onLock: (scene: StudioScene, key: string, value: boolean) => void;
  onRegenerate: (scene: StudioScene) => void;
  onApprove: (scene: StudioScene) => void;
  onGenerate: () => void;
  characterName?: string;
}) {
  if (!scenes.length) {
    return (
      <div className="rounded-2xl border border-dashed border-line p-8 text-sm text-muted">
        Choose a concept first. The storyboard will appear here.
      </div>
    );
  }

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="font-serif text-3xl">Review storyboard</h2>
          <p className="mt-2 text-sm text-muted">
            Edit scenes, lock what must stay the same, then generate only when the plan looks right.
          </p>
          {characterName ? (
            <p className="mt-2 text-sm">
              Primary character: {characterName}. This video uses one character across scenes.
            </p>
          ) : null}
          <div className="mt-3">
            <SecondaryButton
              type="button"
              disabled={pending || !scenes.length}
              onClick={() => {
                const lockAll = !scenes.every((scene) => scene.scene_locked);
                scenes.forEach((scene) => onLock(scene, "scene_locked", lockAll));
              }}
            >
              {scenes.every((scene) => scene.scene_locked) ? "Unlock all scenes" : "Lock all scenes"}
            </SecondaryButton>
          </div>
        </div>
        <div>
          <p className="text-sm font-medium">Length</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {DURATION_OPTIONS.map((value) => (
              <button
                key={value}
                type="button"
                disabled={pending}
                onClick={() => onDuration(value)}
                className={`h-11 min-w-20 rounded-full border px-4 text-sm ${
                  duration === value ? "border-gold bg-gold/15" : "border-line"
                }`}
              >
                {value}s
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-6 grid gap-4">
        {scenes.map((scene, index) => (
          <article
            key={scene.id || scene.scene_key}
            className={`grid gap-4 rounded-2xl border bg-background p-4 md:grid-cols-[6.5rem_minmax(0,1fr)] md:p-4 ${
              selectedKey === scene.scene_key ? "border-primary ring-2 ring-[var(--misa-cyan)]/25" : "border-line"
            }`}
            onClick={() => onSelect?.(scene)}
          >
            <div className="overflow-hidden rounded-2xl bg-black/5">
              {scene.image_url || scene.video_url ? (
                scene.image_url ? (
                  <img src={scene.image_url} alt="" className="aspect-[9/16] w-full object-cover" />
                ) : selectedKey === scene.scene_key && scene.video_url ? (
                  <video src={scene.video_url} className="aspect-[9/16] w-full object-cover" muted playsInline preload="metadata" />
                ) : (
                  <div className="flex aspect-[9/16] items-center justify-center bg-black/10 text-xs text-muted">
                    Clip ready
                  </div>
                )
              ) : (
                <div className="flex aspect-[9/16] items-center justify-center text-xs text-muted">
                  Scene {scene.order || index + 1}
                </div>
              )}
            </div>
            <div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs uppercase tracking-[0.16em] text-muted">
                  Scene {scene.order || index + 1} · {formatClock(scene.start_time)}–{formatClock(scene.end_time)} ·{" "}
                  {scene.duration}s
                </p>
                <span className="text-sm">
                  {sceneStatusIcon(scene.scene_status)} {sceneLabel(scene.scene_status)}
                  {scene.approved ? " · ✓ Approved" : ""}
                </span>
              </div>
              <h3 className="mt-2 font-medium">{scene.title || `Scene ${index + 1}`}</h3>
              <p className="mt-2 text-sm">{sceneShot(scene)}</p>
              <p className="mt-2 text-sm text-muted">Presenter: {scene.presenter_action || "—"}</p>
              <p className="mt-1 text-sm text-muted">
                Camera: {[scene.camera_framing, scene.camera_movement].filter(Boolean).join(" · ") || "—"}
              </p>
              <p className="mt-1 text-sm text-muted">
                Location: {scene.location || scene.background || "—"}
              </p>
              <p className="mt-1 text-sm">VO: {sceneVoice(scene) || "—"}</p>
              <p className="mt-1 text-sm">Caption: {sceneCaption(scene) || "—"}</p>
              <p className="mt-1 text-sm text-muted">
                Benefit: {scene.benefit || scene.approved_claim || "—"}
              </p>
              {scene.error ? <p className="mt-2 text-sm text-red-700">{scene.error}</p> : null}
              <div className="mt-4">
                <LockControls
                  scene={scene}
                  onToggle={(key, value) => onLock(scene, key, value)}
                />
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <SecondaryButton type="button" disabled={pending} onClick={() => onEdit(scene)}>
                  Edit
                </SecondaryButton>
                <SecondaryButton type="button" disabled={pending} onClick={() => onDuplicate(scene)}>
                  Duplicate
                </SecondaryButton>
                <SecondaryButton type="button" disabled={pending || index === 0} onClick={() => onMove(scene, -1)}>
                  Move up
                </SecondaryButton>
                <SecondaryButton
                  type="button"
                  disabled={pending || index === scenes.length - 1}
                  onClick={() => onMove(scene, 1)}
                >
                  Move down
                </SecondaryButton>
                <SecondaryButton type="button" disabled={pending || scenes.length <= 1} onClick={() => onDelete(scene)}>
                  Delete
                </SecondaryButton>
                <SecondaryButton type="button" disabled={pending} onClick={() => onRegenerate(scene)}>
                  {`Regenerate Scene ${String(scene.order || index + 1).padStart(2, "0")}`}
                </SecondaryButton>
                <SecondaryButton type="button" disabled={pending || scene.approved} onClick={() => onApprove(scene)}>
                  {scene.approved ? "Approved" : "Approve scene"}
                </SecondaryButton>
              </div>
            </div>
          </article>
        ))}
      </div>

      <div className="mt-8 flex flex-wrap gap-3">
        <PrimaryButton type="button" disabled={pending} onClick={onGenerate}>
          {pending ? "Starting…" : "Generate video"}
        </PrimaryButton>
      </div>
    </div>
  );
}
