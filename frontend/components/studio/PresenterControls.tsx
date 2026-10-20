"use client";

import { PRESENTER_ETHNICITY_OPTIONS, PRESENTER_PHOTO_ANGLES } from "@/lib/studio";
import type { CreativeBriefForm } from "@/lib/director";

export type PresenterPhotos = Partial<Record<(typeof PRESENTER_PHOTO_ANGLES)[number]["id"], File>>;

export function PresenterControls({
  brief,
  onChange,
  photos,
  onPhotos,
  onSaveAsCharacter,
}: {
  brief: CreativeBriefForm;
  onChange: (next: CreativeBriefForm) => void;
  photos: PresenterPhotos;
  onPhotos: (next: PresenterPhotos) => void;
  onSaveAsCharacter?: () => void;
}) {
  const custom = brief.presenter_ethnicity === "custom";

  return (
    <div className="rounded-2xl border border-line bg-background p-5">
      <h3 className="font-medium">Presenter</h3>
      <p className="mt-1 text-sm text-muted">
        The same face is locked across every scene with a reference photo plus a continuity prompt.
        Uploading your own photos is the most reliable way to keep identity consistent — or pick a look
        and we will generate one identity still and reuse it.
      </p>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        <label className="block text-sm">
          Look / background
          <select
            value={brief.presenter_ethnicity}
            onChange={(event) =>
              onChange({ ...brief, presenter_ethnicity: event.target.value })
            }
            className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
          >
            {PRESENTER_ETHNICITY_OPTIONS.map((option) => (
              <option key={option.id || "any"} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          Extra description
          <input
            value={brief.presenter_look}
            onChange={(event) => onChange({ ...brief, presenter_look: event.target.value })}
            placeholder="Example: late 20s, short hair, casual home clothes"
            className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
          />
        </label>
      </div>
      {custom ? (
        <label className="mt-4 block text-sm">
          Describe the presenter
          <input
            value={brief.presenter_ethnicity_custom}
            onChange={(event) =>
              onChange({ ...brief, presenter_ethnicity_custom: event.target.value })
            }
            placeholder="Example: Malaysian Chinese man, or European woman"
            className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
          />
        </label>
      ) : null}
      <div className="mt-5">
        <p className="text-sm font-medium">Use my photos as the presenter</p>
        <p className="mt-1 text-sm text-muted">
          Optional. Front is best. Left, right, up, and down help keep the face consistent.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {PRESENTER_PHOTO_ANGLES.map((angle) => (
            <label key={angle.id} className="block text-xs">
              {angle.label}
              <input
                type="file"
                accept="image/*"
                className="mt-2 w-full text-xs"
                onChange={(event) => {
                  const file = event.target.files?.[0] || undefined;
                  onPhotos({ ...photos, [angle.id]: file });
                }}
              />
              {photos[angle.id] ? (
                <span className="mt-1 block truncate text-[11px] text-muted">{photos[angle.id]?.name}</span>
              ) : null}
            </label>
          ))}
        </div>
      </div>
      {onSaveAsCharacter ? (
        <button type="button" className="mt-4 text-sm font-medium text-primary" onClick={onSaveAsCharacter}>
          Save as Character
        </button>
      ) : null}
    </div>
  );
}
