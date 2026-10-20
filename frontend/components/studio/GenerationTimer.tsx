"use client";

import { useEffect, useState } from "react";

import type { VideoProject } from "@/lib/api";
import {
  formatGenerationClock,
  generationElapsedMs,
  rememberGenerationStart,
} from "@/lib/studio";

export function GenerationTimer({
  project,
  running,
  size = "md",
  className = "",
  timerKey,
  startedAt,
}: {
  project?: Pick<VideoProject, "id" | "generation_metrics" | "status"> | null;
  running: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
  timerKey?: string | number;
  startedAt?: string | null;
}) {
  const [now, setNow] = useState(() => Date.now());
  const [fallbackStart, setFallbackStart] = useState<number | null>(null);
  const storageKey = timerKey ?? project?.id;
  const timedProject = startedAt
    ? { ...project, id: project?.id, generation_metrics: { ...project?.generation_metrics, started_at: startedAt } }
    : project;

  useEffect(() => {
    if (!running) return;
    setFallbackStart(rememberGenerationStart(storageKey));
  }, [running, storageKey]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  const elapsed = generationElapsedMs(timedProject, now, running, fallbackStart);
  if (!running && elapsed <= 0) return null;

  const clock = formatGenerationClock(elapsed);
  const caption = running ? "Time elapsed" : "Time to generate";

  if (size === "sm") {
    return (
      <p className={`text-sm tabular-nums ${className}`} role="timer" aria-label={`${caption} ${clock}`}>
        <span className="font-semibold">{clock}</span>
        <span className="opacity-75"> {running ? "elapsed" : "to generate"}</span>
      </p>
    );
  }

  const clockClass =
    size === "lg"
      ? "font-serif text-4xl tabular-nums tracking-tight text-foreground"
      : "text-2xl font-semibold tabular-nums text-foreground";

  return (
    <div className={className} role="timer" aria-label={`${caption} ${clock}`}>
      <p className={clockClass}>{clock}</p>
      <p className="mt-1 text-xs text-muted">{caption}</p>
    </div>
  );
}
