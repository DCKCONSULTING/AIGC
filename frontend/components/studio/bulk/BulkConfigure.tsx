"use client";

import { useEffect, useState, type ReactNode } from "react";

import type { Product, StudioCharacter, VideoProject } from "@/lib/api";
import type { BulkStudioMode } from "@/lib/api";
import {
  BULK_COUNT_MAX,
  BULK_COUNT_MIN,
  BULK_LOCK_LABELS,
  BULK_VARIABLE_LABELS,
  REFERENCE_VIDEO_ACCEPT,
  canUseLibraryVideoForBulk,
  configureFields,
  isReferenceMode,
  isSameFlowMode,
  parseBulkCount,
} from "@/lib/bulk-studio";
import { DURATION_OPTIONS, LANGUAGE_OPTIONS, STYLE_OPTIONS } from "@/lib/studio";
import { characterIsVideoReady } from "@/lib/characters";
import { PrimaryButton, SecondaryButton } from "../ui";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid gap-2 text-sm">
      <span className="font-medium">{label}</span>
      {children}
    </label>
  );
}

const selectClass = "h-12 rounded-2xl border border-line bg-card px-3";

export function BulkConfigure({
  mode,
  products,
  characters,
  productId,
  characterId,
  characterIds,
  language,
  speakingStyle,
  duration,
  count,
  locks,
  variables,
  referenceName,
  referenceUrl,
  analyzed,
  pending,
  onProduct,
  onCharacter,
  onCharacters,
  onLanguage,
  onStyle,
  onDuration,
  onCount,
  onToggleVariable,
  onReference,
  videos = [],
  sourceVideoId = "",
  analysis,
  instruction,
  onInstruction,
  onSourceVideo,
  onAnalyze,
  onBack,
  onContinue,
}: {
  mode: BulkStudioMode;
  products: Product[];
  characters: StudioCharacter[];
  productId: number | "";
  characterId: number | "";
  characterIds: number[];
  language: string;
  speakingStyle: string;
  duration: number;
  count: number;
  locks: Record<string, boolean>;
  variables: Record<string, boolean>;
  referenceName: string;
  referenceUrl: string;
  analyzed: boolean;
  pending: boolean;
  onProduct: (id: number) => void;
  onCharacter: (id: number) => void;
  onCharacters: (ids: number[]) => void;
  onLanguage: (value: string) => void;
  onStyle: (value: string) => void;
  onDuration: (value: number) => void;
  onCount: (value: number) => void;
  videos: VideoProject[];
  sourceVideoId: number | "";
  analysis?: Record<string, unknown>;
  instruction: string;
  onInstruction: (value: string) => void;
  onSourceVideo: (id: number) => void;
  onToggleVariable: (key: string) => void;
  onReference: (file: File | null) => void;
  onAnalyze: () => void;
  onBack: () => void;
  onContinue: () => void;
}) {
  const fields = configureFields(mode);
  const readyCharacters = characters.filter((item) => characterIsVideoReady(item));
  const [countDraft, setCountDraft] = useState(String(count));

  useEffect(() => {
    setCountDraft(String(count));
  }, [count]);

  function commitCount(raw: string) {
    const next = parseBulkCount(raw, count);
    setCountDraft(String(next));
    onCount(next);
  }

  return (
    <div className="grid gap-6">
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Product">
          <select className={selectClass} value={productId} onChange={(event) => onProduct(Number(event.target.value))}>
            <option value="">Choose a product</option>
            {products.map((product) => (
              <option key={product.id} value={product.id}>
                {product.name}
              </option>
            ))}
          </select>
        </Field>
        {fields.needsCharacter ? (
          <Field label="Character">
            <select
              className={selectClass}
              value={characterId}
              onChange={(event) => onCharacter(Number(event.target.value))}
            >
              <option value="">Choose a character</option>
              {readyCharacters.map((character) => (
                <option key={character.id} value={character.id}>
                  {character.name}
                </option>
              ))}
            </select>
          </Field>
        ) : null}
        <Field label="Language">
          <span className="-mt-1 text-xs text-muted">Chinese, Cantonese, and Hokkien are separate spoken languages.</span>
          <select className={selectClass} value={language} onChange={(event) => onLanguage(event.target.value)}>
            {LANGUAGE_OPTIONS.map((option) => (
              <option key={option.id} value={option.id} title={option.hint}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Tone">
          <select className={selectClass} value={speakingStyle} onChange={(event) => onStyle(event.target.value)}>
            {STYLE_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Duration">
          <select className={selectClass} value={duration} onChange={(event) => onDuration(Number(event.target.value))}>
            {DURATION_OPTIONS.map((item) => (
              <option key={item} value={item}>
                {item}s · 9:16
              </option>
            ))}
          </select>
        </Field>
        {fields.countEditable ? (
          <Field label="Number of videos">
            <input
              className={selectClass}
              type="number"
              inputMode="numeric"
              min={BULK_COUNT_MIN}
              max={BULK_COUNT_MAX}
              step={1}
              value={countDraft}
              onChange={(event) => {
                const raw = event.target.value;
                setCountDraft(raw);
                if (raw.trim()) commitCount(raw);
              }}
              onBlur={(event) => commitCount(event.target.value)}
            />
            <span className="text-xs text-muted">Type how many videos to create, from {BULK_COUNT_MIN} to {BULK_COUNT_MAX}.</span>
          </Field>
        ) : (
          <p className="self-end text-sm text-muted">{characterIds.length} videos — one per selected character.</p>
        )}
      </div>

      {fields.needsCharacters ? (
        <div>
          <p className="mb-2 text-sm font-medium">Characters</p>
          <div className="grid gap-2 md:grid-cols-2">
            {readyCharacters.map((character) => {
              const checked = characterIds.includes(character.id);
              return (
                <label key={character.id} className="flex items-center gap-3 rounded-2xl border border-line bg-card px-4 py-3">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() =>
                      onCharacters(
                        checked
                          ? characterIds.filter((id) => id !== character.id)
                          : [...characterIds, character.id],
                      )
                    }
                  />
                  <span>{character.name}</span>
                </label>
              );
            })}
          </div>
        </div>
      ) : null}

      {fields.needsSourceVideo ? (
        <div className="rounded-2xl border border-line bg-card p-5">
          <p className="text-sm font-medium">Existing Studio video</p>
          <p className="mt-1 text-sm text-muted">
            This video becomes the master. Copies keep the same story, scenes, timing, dialogue, and CTA unless you mark something variable.
          </p>
          <select
            className={`${selectClass} mt-4 w-full`}
            value={sourceVideoId}
            onChange={(event) => onSourceVideo(Number(event.target.value))}
          >
            <option value="">Select a Studio video</option>
            {videos.filter((item) => canUseLibraryVideoForBulk(item)).map((item) => (
              <option key={item.id} value={item.id}>
                {item.product_name || `Video ${item.id}`}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {fields.needsReference ? (
        <div className="rounded-2xl border border-dashed border-line bg-card p-5">
          <p className="text-sm font-medium">Reference video</p>
          <p className="mt-1 text-sm text-muted">
            Upload an MP4, MOV, or WebM. Analysis runs once and becomes the master specification.
          </p>
          <input
            className="mt-4 block w-full text-sm"
            type="file"
            accept={REFERENCE_VIDEO_ACCEPT}
            onChange={(event) => onReference(event.target.files?.[0] || null)}
          />
          {referenceName ? <p className="mt-2 text-sm">{referenceName}</p> : null}
          {referenceUrl ? (
            <video className="mt-3 max-h-56 w-full rounded-xl bg-black" src={referenceUrl} controls />
          ) : null}
          <SecondaryButton className="mt-4" type="button" disabled={pending || !referenceName} onClick={onAnalyze}>
            {analyzed ? "Re-analyze reference" : "Analyze reference"}
          </SecondaryButton>
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-2xl border border-line bg-card p-4">
          <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-primary">Locked</p>
          <ul className="mt-3 grid gap-2 text-sm">
            {Object.entries(locks)
              .filter(([, value]) => value)
              .map(([key]) => (
                <li key={key}>{BULK_LOCK_LABELS[key] || key}</li>
              ))}
          </ul>
        </div>
        <div className="rounded-2xl border border-line bg-card p-4">
          <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-primary">Variable</p>
          <ul className="mt-3 grid gap-2 text-sm">
            {Object.entries(variables).map(([key, value]) => (
              <li key={key}>
                <label className="flex items-center gap-2">
                  <input type="checkbox" checked={value} disabled={!value && isReferenceMode(mode)} onChange={() => onToggleVariable(key)} />
                  {BULK_VARIABLE_LABELS[key] || key}
                </label>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {analysis && (analysis.flow || analysis.scene_count || analysis.duration) ? (
        <div className="rounded-2xl border border-line bg-card p-5">
          <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-primary">
            {isSameFlowMode(mode) ? "Master flow" : "Video analysis"}
          </p>
          <dl className="mt-3 grid gap-2 text-sm">
            {analysis.duration ? (
              <div>
                <dt className="text-muted">Duration</dt>
                <dd>{String(analysis.duration)} sec</dd>
              </div>
            ) : null}
            {analysis.scene_count ? (
              <div>
                <dt className="text-muted">Scenes</dt>
                <dd>{String(analysis.scene_count)}</dd>
              </div>
            ) : null}
            {analysis.location ? (
              <div>
                <dt className="text-muted">Location</dt>
                <dd>{String(analysis.location)}</dd>
              </div>
            ) : null}
            {analysis.cta ? (
              <div>
                <dt className="text-muted">CTA</dt>
                <dd>{String(analysis.cta)}</dd>
              </div>
            ) : null}
          </dl>
          {Array.isArray(analysis.flow) ? (
            <ol className="mt-4 grid gap-2 text-sm">
              {(analysis.flow as Array<Record<string, unknown>>).map((item, index) => (
                <li key={String(item.order || index)}>
                  {index + 1}. {String(item.title || item.purpose || `Scene ${index + 1}`)}
                  {item.script ? <span className="block text-muted">{String(item.script)}</span> : null}
                </li>
              ))}
            </ol>
          ) : null}
        </div>
      ) : null}

      <label className="block text-sm">
        Instruction
        <span className="ml-2 font-normal text-muted">Optional</span>
        <textarea
          rows={4}
          value={instruction}
          onChange={(event) => onInstruction(event.target.value)}
          placeholder="Optional. If you add notes, they become the source of truth for every story in this batch."
          className="mt-2 w-full rounded-2xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
        />
      </label>

      <div className="flex flex-wrap gap-3">
        <SecondaryButton type="button" onClick={onBack}>
          Back
        </SecondaryButton>
        <PrimaryButton type="button" disabled={pending} onClick={onContinue}>
          Generate variation plan
        </PrimaryButton>
      </div>
    </div>
  );
}
