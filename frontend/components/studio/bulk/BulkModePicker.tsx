"use client";

import type { BulkStudioMode } from "@/lib/api";
import { BULK_MODES } from "@/lib/bulk-studio";
import { ChoiceButton } from "../ui";

export function BulkModePicker({
  selected,
  onSelect,
}: {
  selected: BulkStudioMode | "";
  onSelect: (mode: BulkStudioMode) => void;
}) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {BULK_MODES.map((mode) => (
        <ChoiceButton
          key={mode.id}
          selected={selected === mode.id}
          title={mode.title}
          hint={`${mode.description} ${mode.example}`}
          onClick={() => onSelect(mode.id)}
        />
      ))}
    </div>
  );
}
