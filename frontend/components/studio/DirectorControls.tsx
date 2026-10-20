"use client";

import type { StudioScene } from "@/lib/api";

export function DirectorControls({
  scene,
  onChange,
}: {
  scene: StudioScene;
  onChange: (patch: Partial<StudioScene>) => void;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <label className="block text-sm">
        Camera framing
        <input
          value={scene.camera_framing || ""}
          onChange={(event) => onChange({ camera_framing: event.target.value })}
          placeholder="Close-up, medium, wide"
          className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
        />
      </label>
      <label className="block text-sm">
        Camera movement
        <input
          value={scene.camera_movement || ""}
          onChange={(event) => onChange({ camera_movement: event.target.value })}
          placeholder="Slow push-in"
          className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
        />
      </label>
      <label className="block text-sm">
        Lens / framing
        <input
          value={scene.lens || ""}
          onChange={(event) => onChange({ lens: event.target.value })}
          className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
        />
      </label>
      <label className="block text-sm">
        Lighting
        <input
          value={scene.lighting || ""}
          onChange={(event) => onChange({ lighting: event.target.value })}
          className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
        />
      </label>
      <label className="block text-sm">
        Pace
        <input
          value={scene.pace || ""}
          onChange={(event) => onChange({ pace: event.target.value })}
          className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
        />
      </label>
      <label className="block text-sm">
        Transition
        <input
          value={scene.transition || ""}
          onChange={(event) => onChange({ transition: event.target.value })}
          className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
        />
      </label>
      <label className="block text-sm">
        Depth of field
        <input
          value={scene.depth_of_field || ""}
          onChange={(event) => onChange({ depth_of_field: event.target.value })}
          className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
        />
      </label>
      <label className="block text-sm">
        Composition
        <input
          value={scene.composition || ""}
          onChange={(event) => onChange({ composition: event.target.value })}
          className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
        />
      </label>
      <label className="block text-sm md:col-span-2">
        Sound / music direction
        <input
          value={scene.sound_direction || ""}
          onChange={(event) => onChange({ sound_direction: event.target.value })}
          className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-3 outline-none focus:border-gold"
        />
      </label>
    </div>
  );
}
