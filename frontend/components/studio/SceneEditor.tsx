"use client";

import { useEffect, useState } from "react";

import type { StudioScene } from "@/lib/api";
import { formatClock } from "@/lib/director";
import { DirectorControls } from "./DirectorControls";
import { LockControls } from "./LockControls";
import { PrimaryButton, SecondaryButton } from "./ui";

export function SceneEditor({
  scene,
  pending,
  onSave,
  onCancel,
  onRegenerate,
}: {
  scene: StudioScene;
  pending: boolean;
  onSave: (patch: Partial<StudioScene> & { confirm_approved_edit?: boolean }) => void;
  onCancel: () => void;
  onRegenerate: (confirm?: boolean) => void;
}) {
  const [draft, setDraft] = useState(scene);
  const [directorOpen, setDirectorOpen] = useState(false);

  useEffect(() => {
    setDraft(scene);
  }, [scene]);

  function patch(next: Partial<StudioScene>) {
    setDraft((current) => ({ ...current, ...next }));
  }

  return (
    <div className="fixed inset-0 z-40 flex items-end justify-center bg-black/40 p-4 md:items-center">
      <div className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-[28px] border border-line bg-card p-5 md:p-8">
        <p className="text-xs uppercase tracking-[0.18em] text-gold">
          Scene {scene.order} · {formatClock(scene.start_time)}–{formatClock(scene.end_time)}
        </p>
        <h2 className="mt-2 font-serif text-3xl">{scene.title || `Scene ${scene.order}`}</h2>
        {scene.approved ? (
          <p className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm">
            This scene is approved. Saving will ask you to confirm the change.
          </p>
        ) : null}

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          <label className="block text-sm">
            Start (seconds)
            <input
              type="number"
              min={0}
              value={draft.start_time ?? 0}
              onChange={(event) => patch({ start_time: Number(event.target.value) })}
              className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
            />
          </label>
          <label className="block text-sm">
            End (seconds)
            <input
              type="number"
              min={1}
              value={draft.end_time ?? (draft.duration || 5)}
              onChange={(event) => patch({ end_time: Number(event.target.value) })}
              className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
            />
          </label>
        </div>

        <label className="mt-4 block text-sm">
          Scene description
          <textarea
            rows={3}
            value={draft.shot_description || draft.visual || ""}
            onChange={(event) => patch({ shot_description: event.target.value, visual: event.target.value })}
            className="mt-2 w-full rounded-2xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
          />
        </label>
        <label className="mt-4 block text-sm">
          Presenter action
          <textarea
            rows={2}
            value={draft.presenter_action || ""}
            onChange={(event) => patch({ presenter_action: event.target.value })}
            className="mt-2 w-full rounded-2xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
          />
        </label>
        <label className="mt-4 block text-sm">
          Voice-over
          <textarea
            rows={3}
            value={draft.voice_over || draft.narration || ""}
            onChange={(event) => patch({ voice_over: event.target.value, narration: event.target.value })}
            className="mt-2 w-full rounded-2xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
          />
        </label>
        <label className="mt-4 block text-sm">
          On-screen caption
          <input
            value={draft.on_screen_caption || draft.caption || ""}
            onChange={(event) => patch({ on_screen_caption: event.target.value, caption: event.target.value })}
            className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
          />
        </label>
        <label className="mt-4 block text-sm">
          Location / background
          <input
            value={draft.location || draft.background || ""}
            onChange={(event) => patch({ location: event.target.value, background: event.target.value })}
            className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
          />
        </label>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <label className="block text-sm">
            Camera
            <input
              value={draft.camera_framing || ""}
              onChange={(event) => patch({ camera_framing: event.target.value })}
              placeholder="Close-up, medium, wide"
              className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
            />
          </label>
          <label className="block text-sm">
            Camera movement
            <input
              value={draft.camera_movement || ""}
              onChange={(event) => patch({ camera_movement: event.target.value })}
              placeholder="Slow push-in"
              className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
            />
          </label>
        </div>
        <label className="mt-4 block text-sm">
          Product benefit / approved claim
          <input
            value={draft.benefit || draft.approved_claim || ""}
            onChange={(event) => patch({ benefit: event.target.value, approved_claim: event.target.value })}
            className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
          />
        </label>

        <div className="mt-6">
          <p className="text-sm font-medium">Locks</p>
          <div className="mt-3">
            <LockControls
              scene={draft}
              onToggle={(key, value) => patch({ [key]: value })}
            />
          </div>
        </div>

        <button
          type="button"
          className="mt-6 text-sm text-gold-deep underline-offset-2 hover:underline"
          onClick={() => setDirectorOpen((open) => !open)}
        >
          {directorOpen ? "Hide director controls" : "Director controls"}
        </button>
        {directorOpen ? (
          <div className="mt-4 rounded-2xl border border-line bg-background p-4">
            <DirectorControls scene={draft} onChange={patch} />
          </div>
        ) : null}

        <div className="mt-8 flex flex-wrap gap-3">
          <PrimaryButton
            type="button"
            disabled={pending}
            onClick={() =>
              onSave({
                ...draft,
                confirm_approved_edit: scene.approved ? true : undefined,
              })
            }
          >
            {pending ? "Saving…" : "Save scene"}
          </PrimaryButton>
          <SecondaryButton
            type="button"
            disabled={pending}
            onClick={() => onRegenerate(Boolean(scene.approved))}
          >
            {`Regenerate Scene ${String(scene.order).padStart(2, "0")}`}
          </SecondaryButton>
          <SecondaryButton type="button" onClick={onCancel}>
            Cancel
          </SecondaryButton>
        </div>
      </div>
    </div>
  );
}
