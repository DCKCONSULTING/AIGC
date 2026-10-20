"use client";

import type { BulkVariation } from "@/lib/api";
import { PrimaryButton, SecondaryButton } from "../ui";

export function BulkPlanEditor({
  rows,
  pending,
  instruction,
  onInstruction,
  onChange,
  onRemove,
  onMove,
  onRegenerateItem,
  onRegenerateAll,
  onBack,
  onGenerate,
}: {
  rows: BulkVariation[];
  pending: boolean;
  instruction: string;
  onInstruction: (value: string) => void;
  onChange: (index: number, patch: Partial<BulkVariation>) => void;
  onRemove: (index: number) => void;
  onMove: (index: number, direction: -1 | 1) => void;
  onRegenerateItem: (sequence: number) => void;
  onRegenerateAll: () => void;
  onBack: () => void;
  onGenerate: () => void;
}) {
  return (
    <div className="grid gap-5">
      <ol className="grid gap-3">
        {rows.map((row, index) => (
          <li key={`${row.sequence}-${index}`} className="rounded-2xl border border-line bg-card p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-muted">
                {String(index + 1).padStart(2, "0")}
              </p>
              <div className="flex flex-wrap gap-2">
                <button type="button" className="text-xs text-primary" onClick={() => onMove(index, -1)} disabled={index === 0}>
                  Up
                </button>
                <button
                  type="button"
                  className="text-xs text-primary"
                  onClick={() => onMove(index, 1)}
                  disabled={index === rows.length - 1}
                >
                  Down
                </button>
                <button type="button" className="text-xs text-primary" disabled={pending} onClick={() => onRegenerateItem(Number(row.sequence || index + 1))}>
                  Regenerate
                </button>
                <button type="button" className="text-xs text-[#b71958]" onClick={() => onRemove(index)} disabled={rows.length <= 1}>
                  Remove
                </button>
              </div>
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              <input
                className="h-11 rounded-2xl border border-line px-3"
                value={row.title || ""}
                onChange={(event) => onChange(index, { title: event.target.value })}
                placeholder="Title"
              />
              <input
                className="h-11 rounded-2xl border border-line px-3"
                value={row.location || ""}
                onChange={(event) => onChange(index, { location: event.target.value })}
                placeholder="Location"
              />
              <input
                className="h-11 rounded-2xl border border-line px-3 md:col-span-2"
                value={row.hook || ""}
                onChange={(event) => onChange(index, { hook: event.target.value })}
                placeholder="Hook"
              />
            </div>
          </li>
        ))}
      </ol>
      <label className="block text-sm">
        Instruction
        <span className="ml-2 font-normal text-muted">Optional</span>
        <textarea
          rows={4}
          value={instruction}
          onChange={(event) => onInstruction(event.target.value)}
          placeholder="Optional. If you add notes, they become the source of truth when these stories are generated."
          className="w-full rounded-2xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
        />
      </label>
      <div className="flex flex-wrap gap-3">
        <SecondaryButton type="button" onClick={onBack}>
          Back
        </SecondaryButton>
        <SecondaryButton type="button" disabled={pending} onClick={onRegenerateAll}>
          Regenerate plan
        </SecondaryButton>
        <PrimaryButton type="button" disabled={pending || !rows.length} onClick={onGenerate}>
          Generate {rows.length} video{rows.length === 1 ? "" : "s"}
        </PrimaryButton>
      </div>
    </div>
  );
}
