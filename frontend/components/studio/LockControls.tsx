"use client";

import type { StudioScene } from "@/lib/api";

const LOCKS = [
  { key: "scene_locked", label: "Scene" },
  { key: "product_locked", label: "Product" },
  { key: "presenter_locked", label: "Presenter" },
  { key: "location_locked", label: "Location" },
  { key: "script_locked", label: "Script" },
  { key: "caption_locked", label: "Caption" },
] as const;

export function LockControls({
  scene,
  onToggle,
}: {
  scene: StudioScene;
  onToggle: (key: (typeof LOCKS)[number]["key"], value: boolean) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {LOCKS.map((item) => {
        const locked = Boolean(scene[item.key]);
        return (
          <button
            key={item.key}
            type="button"
            onClick={() => onToggle(item.key, !locked)}
            className={`h-9 rounded-full border px-3 text-xs ${
              locked ? "border-gold bg-gold/15" : "border-line"
            }`}
          >
            {locked ? "Locked" : "Unlocked"} {item.label}
          </button>
        );
      })}
    </div>
  );
}
