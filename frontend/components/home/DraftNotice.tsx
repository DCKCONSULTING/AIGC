"use client";

import { useSyncExternalStore } from "react";

import { hasHomeDraft, readHomeDraft } from "@/lib/home";

function subscribe() {
  return () => {};
}

function getSnapshot() {
  return hasHomeDraft(readHomeDraft());
}

function getServerSnapshot() {
  return false;
}

export function DraftNotice() {
  const visible = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  if (!visible) return null;
  return (
    <p className="mt-5 rounded-2xl border border-[#cae0fa] bg-[#f0f8ff] px-4 py-3 text-sm text-[var(--misa-navy)]">
      Your idea is saved. After this step, MiSa will open Studio with your prompt and photos.
    </p>
  );
}
