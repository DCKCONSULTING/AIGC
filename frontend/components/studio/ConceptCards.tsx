"use client";

import type { CreativeConcept, StudioCharacter } from "@/lib/api";
import { characterIsVideoReady } from "@/lib/characters";
import { formatClock } from "@/lib/director";
import {
  BULK_GENDER_MODES,
  DURATION_OPTIONS,
  STUDIO_BULK_MAX,
  type BulkDurationMode,
  type BulkGenderMode,
} from "@/lib/studio";
import { PrimaryButton, SecondaryButton } from "./ui";

export function ConceptCards({
  concepts,
  selectedId,
  selectedConceptIds,
  mixing,
  pending,
  duration,
  durationMode,
  genderMode,
  videoCount,
  combinationCount,
  bulkError,
  characters,
  selectedCharacterIds,
  generateCharacter,
  onToggleConcept,
  onSelectAllConcepts,
  onDuration,
  onDurationMode,
  onGenderMode,
  onVideoCount,
  onToggleCharacter,
  onGenerateCharacter,
  onEdit,
  onMix,
  onToggleMixScene,
  mixKeys,
  onApplyMix,
  onRegenerate,
  onBulkGenerate,
  onBulkGenerateFast,
  pendingFast = false,
}: {
  concepts: CreativeConcept[];
  selectedId?: string;
  selectedConceptIds: string[];
  mixing: boolean;
  pending: boolean;
  duration?: number;
  durationMode: BulkDurationMode;
  genderMode: BulkGenderMode;
  videoCount: number;
  combinationCount: number;
  bulkError: string;
  characters: StudioCharacter[];
  selectedCharacterIds: string[];
  generateCharacter: boolean;
  onToggleConcept: (id: string) => void;
  onSelectAllConcepts: (ids: string[]) => void;
  onDuration?: (value: number) => void;
  onDurationMode: (value: BulkDurationMode) => void;
  onGenderMode: (value: BulkGenderMode) => void;
  onVideoCount: (value: number) => void;
  onToggleCharacter: (id: string) => void;
  onGenerateCharacter: (value: boolean) => void;
  onEdit: (id: string) => void;
  onMix: () => void;
  onToggleMixScene: (conceptId: string, sceneKey: string) => void;
  mixKeys: string[];
  onApplyMix: () => void;
  onRegenerate: () => void;
  onBulkGenerate: () => void;
  onBulkGenerateFast?: () => void;
  pendingFast?: boolean;
}) {
  if (!concepts.length) {
    return (
      <div className="rounded-2xl border border-line bg-background p-6 text-sm text-muted">
        Creative concepts will appear here after you complete the brief.
      </div>
    );
  }

  const allSelected = concepts.every((item) => selectedConceptIds.includes(item.id));
  const busy = pending || pendingFast;
  const canGenerate = !busy && !bulkError && selectedConceptIds.length > 0 && videoCount > 0;
  const storyGap = videoCount !== concepts.length;

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-serif text-3xl">Choose stories for this product</h2>
          <p className="mt-2 text-sm text-muted">
            Select one or more scenarios, then generate them together. Open Edit only if you need to change a
            storyboard before a single video.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <SecondaryButton type="button" disabled={busy} onClick={onMix}>
            {mixing ? "Cancel mix" : "Mix & Edit"}
          </SecondaryButton>
          <PrimaryButton type="button" disabled={busy} onClick={onRegenerate}>
            {pending && !pendingFast
              ? "Creating stories…"
              : `Regenerate ${videoCount} stor${videoCount === 1 ? "y" : "ies"}`}
          </PrimaryButton>
        </div>
      </div>

      <section className="mt-6 grid gap-5 rounded-[24px] border border-line bg-background p-5">
        <div>
          <h3 className="font-medium">Characters</h3>
          <p className="mt-1 text-sm text-muted">
            Use one character, several characters, or a saved character plus a generated one.
          </p>
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {characters.map((item) => {
              const ready = characterIsVideoReady(item);
              const checked = selectedCharacterIds.includes(String(item.id));
              return (
                <label
                  key={item.id}
                  className={`flex items-start gap-3 rounded-2xl border px-3 py-3 text-sm ${
                    checked ? "border-gold bg-gold/10" : "border-line"
                  } ${ready ? "" : "opacity-60"}`}
                >
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4"
                    checked={checked}
                    disabled={pending || !ready}
                    onChange={() => onToggleCharacter(String(item.id))}
                  />
                  <span>
                    <span className="font-medium">{item.name}</span>
                    <span className="mt-0.5 block text-xs text-muted">
                      {item.gender}
                      {item.brand_name ? ` · ${item.brand_name}` : ""}
                      {ready ? "" : " · master required"}
                    </span>
                  </span>
                </label>
              );
            })}
            {!characters.length ? (
              <p className="text-sm text-muted">No saved characters yet. Check Generate character.</p>
            ) : null}
          </div>
          <label className="mt-3 flex items-start gap-3 text-sm">
            <input
              type="checkbox"
              className="mt-1 h-4 w-4"
              checked={generateCharacter}
              disabled={busy}
              onChange={(event) => onGenerateCharacter(event.target.checked)}
            />
            <span>
              <span className="font-medium">Generate character</span>
              <span className="mt-0.5 block text-muted">
                Create a new on-camera person for some or all of these videos.
              </span>
            </span>
          </label>
        </div>

        <div>
          <h3 className="font-medium">Gender</h3>
          <p className="mt-1 text-sm text-muted">Saved characters keep their own look. This applies to generated characters.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {BULK_GENDER_MODES.map((option) => (
              <button
                key={option.id}
                type="button"
                disabled={busy}
                onClick={() => onGenderMode(option.id)}
                className={`h-11 rounded-full border px-4 text-sm ${
                  genderMode === option.id ? "border-gold bg-gold/15" : "border-line"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <h3 className="font-medium">Duration</h3>
          <p className="mt-1 text-sm text-muted">Use one length for every video, or Mix to rotate 15 / 30 / 45 / 60 seconds.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {DURATION_OPTIONS.map((value) => (
              <button
                key={value}
                type="button"
                disabled={busy}
                onClick={() => {
                  onDurationMode("fixed");
                  onDuration?.(value);
                }}
                className={`h-11 min-w-16 rounded-full border px-3 text-sm ${
                  durationMode === "fixed" && duration === value ? "border-gold bg-gold/15" : "border-line"
                }`}
              >
                {value}s
              </button>
            ))}
            <button
              type="button"
              disabled={busy}
              onClick={() => onDurationMode("mix")}
              className={`h-11 rounded-full border px-4 text-sm ${
                durationMode === "mix" ? "border-gold bg-gold/15" : "border-line"
              }`}
            >
              Mix
            </button>
          </div>
        </div>

        <label className="block max-w-xs text-sm">
          How many videos
          <input
            type="number"
            min={1}
            max={STUDIO_BULK_MAX}
            value={videoCount}
            disabled={busy}
            onChange={(event) => onVideoCount(Number(event.target.value || 1))}
            className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
          />
          <span className="mt-1 block text-xs text-muted">
            {combinationCount
              ? `${combinationCount} combination${combinationCount === 1 ? "" : "s"} from selected stories and characters. Max ${STUDIO_BULK_MAX}.`
              : `Up to ${STUDIO_BULK_MAX} videos in one run.`}
          </span>
        </label>
      </section>

      {storyGap ? (
        <div className="mt-5 flex flex-wrap items-center justify-between gap-4 rounded-[24px] border border-amber-200 bg-amber-50 px-5 py-4">
          <div>
            <p className="font-medium">
              {concepts.length} stor{concepts.length === 1 ? "y" : "ies"} ready, {videoCount} requested
            </p>
            <p className="mt-1 text-sm text-muted">
              Change the number, then regenerate so this product has {videoCount} different stories to generate from.
            </p>
          </div>
          <PrimaryButton type="button" disabled={busy} onClick={onRegenerate}>
            {pending ? "Creating stories…" : `Regenerate ${videoCount} stories`}
          </PrimaryButton>
        </div>
      ) : null}

      {mixing ? (
        <p className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm">
          Tick the scenes you want, then apply the mix. This opens the storyboard for that one video.
        </p>
      ) : null}

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">
          {selectedConceptIds.length} of {concepts.length} stories selected
        </p>
        <button
          type="button"
          className="text-sm font-medium text-primary"
          onClick={() => onSelectAllConcepts(allSelected ? [] : concepts.map((item) => item.id))}
        >
          {allSelected ? "Clear stories" : "Select all stories"}
        </button>
      </div>

      <div className="mt-4 grid gap-5 lg:grid-cols-3">
        {concepts.map((concept) => {
          const checked = selectedConceptIds.includes(concept.id);
          return (
            <article
              key={concept.id}
              className={`flex flex-col rounded-[24px] border p-5 ${
                checked || selectedId === concept.id ? "border-gold bg-gold/10" : "border-line bg-background"
              }`}
            >
              <label className="flex items-start gap-3 text-sm">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4"
                  checked={checked}
                  disabled={busy}
                  onChange={() => onToggleConcept(concept.id)}
                />
                <span>
                  <span className="text-xs uppercase tracking-[0.18em] text-gold">{concept.style}</span>
                  <h3 className="mt-1 font-serif text-2xl">{concept.title}</h3>
                </span>
              </label>
              <p className="mt-2 text-sm text-muted">{concept.strategy}</p>
              <p className="mt-4 text-sm">
                <span className="text-muted">Hook · </span>
                {concept.hook}
              </p>
              <div className="mt-4 grid gap-2">
                {(concept.scenes || []).slice(0, 6).map((scene, index) => {
                  const key = `${concept.id}:${scene.scene_key || index}`;
                  const mixChecked = mixKeys.includes(key);
                  return (
                    <label
                      key={key}
                      className="flex items-start gap-2 rounded-xl border border-line/70 px-3 py-2 text-sm"
                    >
                      {mixing ? (
                        <input
                          type="checkbox"
                          checked={mixChecked}
                          onChange={() => onToggleMixScene(concept.id, String(scene.scene_key || ""))}
                        />
                      ) : (
                        <span className="text-xs text-muted">{index + 1}</span>
                      )}
                      <span>{scene.shot_description || scene.title || `Scene ${index + 1}`}</span>
                    </label>
                  );
                })}
              </div>
              <p className="mt-4 text-sm text-muted">
                {concept.scenes?.length || 0} scenes · {formatClock(concept.estimated_duration)} · {concept.cta}
              </p>
              <p className="mt-2 text-sm">{concept.why_it_works}</p>
              <div className="mt-5">
                <SecondaryButton type="button" disabled={busy} onClick={() => onEdit(concept.id)}>
                  Edit storyboard
                </SecondaryButton>
              </div>
            </article>
          );
        })}
      </div>
      {mixing ? (
        <div className="mt-6">
          <PrimaryButton type="button" disabled={pending || mixKeys.length === 0} onClick={onApplyMix}>
            Apply mix
          </PrimaryButton>
        </div>
      ) : null}

      <div className="mt-8 flex flex-col gap-4 rounded-[24px] border border-line bg-card px-5 py-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
        <div className="min-w-0 flex-1">
          <p className="font-medium">
            Generate {videoCount} video{videoCount === 1 ? "" : "s"} in parallel
          </p>
          <p className="mt-1 text-sm text-muted">
            {bulkError ||
              `${selectedConceptIds.length} stor${selectedConceptIds.length === 1 ? "y" : "ies"} generate together · ${
                selectedCharacterIds.length + (generateCharacter ? 1 : 0)
              } character slot${selectedCharacterIds.length + (generateCharacter ? 1 : 0) === 1 ? "" : "s"} · ${
                durationMode === "mix" ? "mixed durations" : `${duration}s`
              }`}
          </p>
        </div>
        <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row sm:flex-wrap sm:justify-end">
          <PrimaryButton type="button" disabled={!canGenerate} onClick={onBulkGenerate}>
            {pending && !pendingFast
              ? "Starting…"
              : `Generate ${videoCount} video${videoCount === 1 ? "" : "s"}`}
          </PrimaryButton>
          {onBulkGenerateFast ? (
            <SecondaryButton type="button" disabled={!canGenerate} onClick={onBulkGenerateFast}>
              {pendingFast ? "Starting Fast…" : "Fast generation"}
            </SecondaryButton>
          ) : null}
        </div>
      </div>
    </div>
  );
}
