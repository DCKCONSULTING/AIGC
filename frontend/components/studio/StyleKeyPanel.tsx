"use client";

import { useMemo, useState } from "react";

import type { Product, StyleRecipe, StudioCharacter } from "@/lib/api";
import { characterIsVideoReady } from "@/lib/characters";
import { bulkCreationState } from "@/lib/studio";
import { PrimaryButton, SecondaryButton } from "./ui";

export function StyleKeyPanel({
  recipes,
  selectedKey,
  onSelectKey,
  products,
  pending,
  onApply,
  onBulk,
  characters = [],
  onSave,
  canSave,
  note,
}: {
  recipes: StyleRecipe[];
  selectedKey: string;
  onSelectKey: (key: string) => void;
  products: Product[];
  pending: boolean;
  onApply: (recipe: StyleRecipe) => void;
  onBulk: (
    recipe: StyleRecipe,
    productIds: number[],
    extras: { location?: string; ethnicity?: string; characterId?: string },
  ) => void;
  characters?: StudioCharacter[];
  onSave?: (name: string, key: string) => void;
  canSave?: boolean;
  note?: string;
}) {
  const selected = recipes.find((item) => item.key === selectedKey || String(item.id) === selectedKey) || null;
  const [bulkOpen, setBulkOpen] = useState(false);
  const [productIds, setProductIds] = useState<number[]>([]);
  const [location, setLocation] = useState("");
  const [ethnicity, setEthnicity] = useState("");
  const [bulkCharacterId, setBulkCharacterId] = useState("");
  const [saveName, setSaveName] = useState("");
  const selectedCount = productIds.length;
  const selectedCharacter = characters.find((item) => String(item.id) === bulkCharacterId) || null;
  const recipeDuration = Number((selected?.recipe as { duration_seconds?: number } | undefined)?.duration_seconds || 0);
  const bulk = bulkCreationState({
    pending,
    styleSelected: Boolean(selected),
    productCount: selectedCount,
    characterId: bulkCharacterId,
    characterName: selectedCharacter?.name,
    characterHasVisual: selectedCharacter ? characterIsVideoReady(selectedCharacter) : true,
    characterBrandId: selectedCharacter?.brand ?? null,
    productBrandIds: products.filter((item) => productIds.includes(item.id)).map((item) => item.brand),
    duration: recipeDuration || null,
    voiceReady: true,
    masterQaPassed: Boolean(
      selected &&
        (selected.source_qa_status === "passed" ||
          selected.source_qa_status === "pass" ||
          (selected.recipe as { master_qa_passed?: boolean } | undefined)?.master_qa_passed),
    ),
  });
  const options = useMemo(
    () => recipes.map((item) => ({ id: String(item.id), key: item.key, label: `${item.key} — ${item.name}` })),
    [recipes],
  );

  return (
    <div className="rounded-2xl border border-line bg-background p-5">
      <h3 className="font-medium">Style key</h3>
      <p className="mt-1 text-sm text-muted">
        Save a video you like, then reuse that quality on other products. Change the presenter, tone, or
        background without rebuilding the 5-scene structure.
      </p>
      <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
        <label className="block text-sm">
          Saved styles
          <select
            value={selected ? String(selected.id) : ""}
            onChange={(event) => onSelectKey(event.target.value)}
            className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
          >
            <option value="">Choose a style key</option>
            {options.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-end">
          <SecondaryButton type="button" disabled={!selected || pending} onClick={() => selected && onApply(selected)}>
            Use this style
          </SecondaryButton>
        </div>
      </div>
      {onSave ? (
        <div className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
          <label className="block text-sm">
            Save current video as a style key
            <input
              value={saveName}
              onChange={(event) => setSaveName(event.target.value)}
              placeholder="Example: Air fryer kitchen UGC"
              className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
            />
          </label>
          <div className="flex items-end">
            <PrimaryButton
              type="button"
              disabled={pending || !canSave || !saveName.trim()}
              onClick={() => onSave(saveName.trim(), "")}
            >
              Save style
            </PrimaryButton>
          </div>
        </div>
      ) : null}
      {note ? <p className="mt-3 text-sm text-muted">{note}</p> : null}
      <button
        type="button"
        className="mt-4 text-sm font-medium text-primary"
        onClick={() => setBulkOpen((open) => !open)}
      >
        {bulkOpen ? "Hide bulk create" : "Bulk create similar videos"}
      </button>
      {bulkOpen ? (
        <div className="mt-4 grid gap-4 rounded-xl border border-line p-4">
          <label className="block text-sm">
            Products to generate
            <select
              multiple
              value={productIds.map(String)}
              onChange={(event) =>
                setProductIds(Array.from(event.target.selectedOptions).map((item) => Number(item.value)))
              }
              className="mt-2 min-h-32 w-full rounded-xl border border-line bg-card px-3 py-2 outline-none focus:border-gold"
            >
              {products.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <span className="mt-1 block text-xs text-muted">Hold Ctrl or Cmd to select more than one. Up to 10.</span>
          </label>
          {characters.length ? (
            <label className="block text-sm">
              Character
              <select
                value={bulkCharacterId}
                onChange={(event) => setBulkCharacterId(event.target.value)}
                className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
              >
                <option value="">No character selected</option>
                {characters.filter((item) => characterIsVideoReady(item) || String(item.id) === bulkCharacterId).map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                    {characterIsVideoReady(item) ? "" : " (master required)"}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label className="block text-sm">
            Different background (optional)
            <input
              value={location}
              onChange={(event) => setLocation(event.target.value)}
              placeholder="Example: a different kitchen"
              className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
            />
          </label>
          <label className="block text-sm">
            Different presenter look (optional)
            <input
              value={ethnicity}
              onChange={(event) => setEthnicity(event.target.value)}
              placeholder="Example: European female, or Malaysian Chinese male"
              className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
            />
          </label>
          <div className="text-sm">
            <p className="font-medium">Requirements</p>
            <ul className="mt-2 grid gap-1">
              {bulk.requirements
                .filter((item) => item.id !== "character" || bulkCharacterId)
                .map((item) => (
                  <li key={item.id}>
                    {item.ok ? "✓" : "•"} {item.label}
                  </li>
                ))}
            </ul>
            {bulk.missing ? <p className="mt-3 text-sm">{bulk.missing}</p> : null}
            {selectedCharacter && !bulk.requirements.find((item) => item.id === "visual")?.ok ? (
              <a href={`/brand/characters/${selectedCharacter.id}`} className="mt-2 inline-flex text-sm underline">
                Edit Character
              </a>
            ) : null}
          </div>
          <PrimaryButton
            type="button"
            disabled={!bulk.enabled}
            onClick={() =>
              selected &&
              bulk.enabled &&
              onBulk(selected, productIds.slice(0, 10), {
                location: location.trim(),
                ethnicity: ethnicity.trim(),
                characterId: bulkCharacterId,
              })
            }
          >
            {pending ? "Starting…" : `Create ${selectedCount || ""} video${selectedCount === 1 ? "" : "s"}`}
          </PrimaryButton>
        </div>
      ) : null}
    </div>
  );
}

export function SaveStyleBox({
  pending,
  onSave,
}: {
  pending: boolean;
  onSave: (name: string) => void;
}) {
  const [name, setName] = useState("");
  return (
    <div className="rounded-2xl border border-line bg-background p-5">
      <h3 className="font-medium">Save this look as a style key</h3>
      <p className="mt-1 text-sm text-muted">
        Reuse the same scene quality later. You can still swap presenter, tone, or kitchen.
      </p>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className="min-w-56 flex-1 text-sm">
          Style name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Air fryer kitchen UGC"
            className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
          />
        </label>
        <PrimaryButton type="button" disabled={pending || !name.trim()} onClick={() => onSave(name.trim())}>
          Save style key
        </PrimaryButton>
      </div>
    </div>
  );
}
