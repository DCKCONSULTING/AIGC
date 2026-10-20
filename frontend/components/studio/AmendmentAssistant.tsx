"use client";

import { useEffect, useState } from "react";

import type { AmendmentRecommendation } from "@/lib/api";
import { formatClock } from "@/lib/director";
import { PrimaryButton, SecondaryButton } from "./ui";

export function AmendmentAssistant({
  recommendations,
  pending,
  qaIncomplete,
  onApply,
  onIgnore,
}: {
  recommendations: AmendmentRecommendation[];
  pending: boolean;
  qaIncomplete?: boolean;
  onApply: (ids: string[], edits: Record<string, string>) => void;
  onIgnore: () => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const [edits, setEdits] = useState<Record<string, string>>({});

  useEffect(() => {
    setSelected(recommendations.filter((item) => item.selected).map((item) => item.id));
    setEdits(
      Object.fromEntries(
        recommendations.map((item) => [item.id, item.editable_text || item.suggested_amendment]),
      ),
    );
  }, [recommendations]);

  if (!recommendations.length) {
    return (
      <p className="mt-6 text-sm text-muted">
        {qaIncomplete
          ? "The video is already saved in Videos. AI visual review has not finished, so approval is waiting. Run AI Review again — this does not remake the video."
          : "No automatic improvements were suggested. You can still approve the video or make a correction."}
      </p>
    );
  }

  return (
    <div className="mt-8">
      <h3 className="font-serif text-2xl">Suggested improvements</h3>
      <p className="mt-2 text-sm text-muted">
        We reviewed the result and found up to three useful changes. Select the ones you want.
        You can type a locale here too — Cantonese, Chinese (Mandarin), or Hokkien — and captions must match the spoken sentence.
      </p>
      <div className="mt-5 grid gap-4">
        {recommendations.map((item) => {
          const checked = selected.includes(item.id);
          return (
            <article key={item.id} className="rounded-2xl border border-line p-4">
              <label className="flex items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={checked}
                  onChange={() =>
                    setSelected((current) =>
                      current.includes(item.id)
                        ? current.filter((id) => id !== item.id)
                        : [...current, item.id],
                    )
                  }
                />
                <div className="min-w-0 flex-1">
                  <p className="text-xs uppercase tracking-[0.16em] text-gold">
                    {item.type} · {item.severity}
                    {item.start != null ? ` · ${formatClock(item.start)}–${formatClock(item.end)}` : ""}
                  </p>
                  <p className="mt-2 font-medium">{item.detected_problem}</p>
                  <p className="mt-1 text-sm text-muted">{item.expected_benefit}</p>
                  {item.reason ? <p className="mt-1 text-xs text-muted">Reason: {item.reason}</p> : null}
                  <p className="mt-1 text-xs text-muted">
                    {item.affected_scenes?.length ? `Scenes: ${item.affected_scenes.join(", ")}` : ""}
                    {item.needs_regeneration === false
                      ? " · Reassemble only"
                      : " · Scene regeneration required"}
                  </p>
                  <textarea
                    rows={3}
                    value={edits[item.id] || ""}
                    onChange={(event) => setEdits((current) => ({ ...current, [item.id]: event.target.value }))}
                    className="mt-3 w-full rounded-2xl border border-line bg-background px-3 py-2 text-sm outline-none focus:border-gold"
                  />
                </div>
              </label>
            </article>
          );
        })}
      </div>
      <div className="mt-5 flex flex-wrap gap-3">
        <PrimaryButton
          type="button"
          disabled={pending || selected.length === 0}
          onClick={() => onApply(selected, edits)}
        >
          {pending ? "Applying…" : "Apply selected"}
        </PrimaryButton>
        <SecondaryButton
          type="button"
          disabled={pending}
          onClick={() => onApply(recommendations.map((item) => item.id), edits)}
        >
          Apply all
        </SecondaryButton>
        <SecondaryButton type="button" disabled={pending} onClick={onIgnore}>
          Ignore
        </SecondaryButton>
      </div>
    </div>
  );
}
