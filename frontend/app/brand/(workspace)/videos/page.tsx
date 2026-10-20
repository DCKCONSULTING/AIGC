"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { api, endpoints, type VideoProject, type VideoStatus } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { GenerationTimer } from "@/components/studio/GenerationTimer";
import { bulkFromLibraryHref, canUseLibraryVideoForBulk } from "@/lib/bulk-studio";
import {
  ACTIVE_STATUSES,
  LIBRARY_PAGE_SIZE,
  LIBRARY_STATUS_FILTERS,
  beginGenerationTimer,
  historyKind,
  isLibraryVideo,
  languageLabel,
  libraryDownloadName,
  libraryPageCount,
  libraryPageItems,
  libraryPageNumbers,
  libraryPosterSrc,
  libraryVideoSrc,
  generationFailureView,
  matchesLibraryFilter,
  merchantError,
  projectCanApprove,
  projectPrimaryAction,
  regenerationFailureNotice,
  sceneRetryBlocked,
  type LibraryStatusFilter,
} from "@/lib/studio";

function videoSrc(item: VideoProject) {
  return libraryVideoSrc(item);
}

function whenLabel(item: VideoProject) {
  const raw = item.updated_at || item.created_at;
  if (!raw) return "";
  return new Date(raw).toLocaleString("en-MY", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusTone(status: string) {
  if (status === "failed") return "bg-[#fff0f6] text-[#b71958]";
  if (status === "approved" || status === "exported") return "bg-[#e7fbff] text-[#08798d]";
  if (ACTIVE_STATUSES.has(status)) return "bg-[#fff8dd] text-[#88620c]";
  return "bg-[#f0f3f7] text-muted";
}

function BulkFromVideoLink({
  item,
  className,
}: {
  item: VideoProject;
  className: string;
}) {
  const ready = canUseLibraryVideoForBulk(item);
  const href = bulkFromLibraryHref(item);
  if (!href) return null;
  return (
    <Link
      href={href}
      aria-disabled={!ready}
      onClick={(event) => {
        if (!ready) event.preventDefault();
      }}
      className={`${className} ${ready ? "" : "pointer-events-none opacity-50"}`}
    >
      Use for bulk
    </Link>
  );
}

function StatusBadge({ item }: { item: VideoProject }) {
  const label =
    item.status === "failed"
      ? "Generation failed"
      : ACTIVE_STATUSES.has(item.status) && item.stage_label
        ? item.stage_label
        : historyKind(item.status);
  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-medium ${statusTone(item.status)}`}>
      {label}
    </span>
  );
}

async function downloadLibraryVideo(item: VideoProject) {
  const src = videoSrc(item);
  if (!src) throw new Error("This video is not ready to download yet.");
  const name = libraryDownloadName(item);
  try {
    const response = await fetch(src);
    if (!response.ok) throw new Error("Unable to download this video.");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch {
    const link = document.createElement("a");
    link.href = src;
    link.download = name;
    link.rel = "noreferrer";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }
}

function VideosContent() {
  const { token } = useAuth();
  const searchParams = useSearchParams();
  const [videos, setVideos] = useState<VideoProject[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [amendment, setAmendment] = useState("");
  const [pending, setPending] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<VideoProject | null>(null);
  const [confirmFailed, setConfirmFailed] = useState(false);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<LibraryStatusFilter>("all");
  const [languageFilter, setLanguageFilter] = useState("");
  const [page, setPage] = useState(1);
  const [downloadingId, setDownloadingId] = useState<number | null>(null);
  const [playingId, setPlayingId] = useState<number | null>(null);

  const activeIds = useMemo(
    () => videos.filter((item) => ACTIVE_STATUSES.has(item.status)).map((item) => item.id),
    [videos],
  );
  const library = useMemo(
    () =>
      videos
        .filter(isLibraryVideo)
        .sort((a, b) => {
          const later = Date.parse(b.updated_at || b.created_at || "") || 0;
          const earlier = Date.parse(a.updated_at || a.created_at || "") || 0;
          if (later !== earlier) return later - earlier;
          return (b.id || 0) - (a.id || 0);
        }),
    [videos],
  );
  const languages = useMemo(
    () =>
      Array.from(new Set(library.map((item) => item.language).filter(Boolean))).sort((a, b) =>
        languageLabel(a).localeCompare(languageLabel(b)),
      ),
    [library],
  );
  const filtered = useMemo(
    () =>
      library.filter((item) =>
        matchesLibraryFilter(item, { query, status: statusFilter, language: languageFilter }),
      ),
    [languageFilter, library, query, statusFilter],
  );
  const pageCount = libraryPageCount(filtered.length);
  const currentPage = Math.min(page, pageCount);
  const visible = libraryPageItems(filtered, currentPage);
  const selected = filtered.find((item) => item.id === selectedId) || filtered[0] || null;
  const generating = Boolean(selected && ACTIVE_STATUSES.has(selected.status));
  const selectedSrc = selected ? videoSrc(selected) : "";
  const selectedPoster = selected ? libraryPosterSrc(selected) : "";

  function playLibraryVideo(item: VideoProject) {
    setSelectedId(item.id);
    setPlayingId(item.id);
  }
  const rangeStart = filtered.length ? (currentPage - 1) * LIBRARY_PAGE_SIZE + 1 : 0;
  const rangeEnd = Math.min(currentPage * LIBRARY_PAGE_SIZE, filtered.length);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    async function load() {
      try {
        const rows = await api<VideoProject[]>(endpoints.ai.videos, { token });
        if (cancelled) return;
        setVideos(rows);
        const next = rows.filter(isLibraryVideo);
        const fromQuery = Number(searchParams.get("id") || "");
        setSelectedId((current) => {
          if (fromQuery && next.some((item) => item.id === fromQuery)) return fromQuery;
          if (current && next.some((item) => item.id === current)) return current;
          return next[0]?.id ?? null;
        });
        setError("");
      } catch {
        if (!cancelled) setError("Unable to load videos.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [token, searchParams]);

  useEffect(() => {
    if (!token || !selectedId) return;
    const current = videos.find((item) => item.id === selectedId);
    if (current?.scenes) return;
    let cancelled = false;
    api<VideoProject>(endpoints.ai.videoDetail(selectedId), { token })
      .then((full) => {
        if (cancelled) return;
        setVideos((rows) => rows.map((item) => (item.id === full.id ? full : item)));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [token, selectedId]);

  useEffect(() => {
    if (!token || !activeIds.length) return;
    const timer = window.setInterval(async () => {
      const rows = await Promise.all(
        activeIds.map(async (id) => {
          try {
            return await api<VideoStatus>(endpoints.ai.videoStatus(id), { token });
          } catch {
            return null;
          }
        }),
      );
      setVideos((current) =>
        current.map((item) => {
          const status = rows.find((row) => row && row.id === item.id);
          return status ? { ...item, ...status } : item;
        }),
      );
      const selectedStatus = rows.find((row) => row && row.id === selectedId);
      if (selectedStatus && (!ACTIVE_STATUSES.has(selectedStatus.status) || selectedStatus.preview_url)) {
        try {
          const full = await api<VideoProject>(endpoints.ai.videoDetail(selectedStatus.id), { token });
          setVideos((current) => current.map((item) => (item.id === full.id ? full : item)));
        } catch {
          /* keep the status row */
        }
      }
    }, 4000);
    return () => window.clearInterval(timer);
  }, [token, activeIds.join(","), selectedId]);

  useEffect(() => {
    setPage(1);
  }, [query, statusFilter, languageFilter]);

  useEffect(() => {
    if (selectedId && !filtered.some((item) => item.id === selectedId)) {
      setSelectedId(filtered[0]?.id ?? null);
    }
  }, [filtered, selectedId]);

  async function regenerate() {
    if (!selected || generating) return;
    setError("");
    setPending(true);
    beginGenerationTimer(selected.id);
    try {
      const updated = await api<VideoProject>(endpoints.ai.videoRegenerate(selected.id), {
        method: "POST",
        token,
        body: JSON.stringify({ instruction: amendment.trim() }),
      });
      setVideos((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setSelectedId(updated.id);
      setAmendment("");
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to regenerate this video."));
    } finally {
      setPending(false);
    }
  }

  async function stopGeneration() {
    if (!selected || !generating || !token) return;
    setError("");
    setPending(true);
    try {
      const result = await api<{ project: VideoProject; stopped_ids: number[] }>(
        endpoints.ai.videoCancel(selected.id),
        { method: "POST", token, body: JSON.stringify({ cancel_batch: true }) },
      );
      const stopped = new Set(result.stopped_ids || [result.project.id]);
      setVideos((current) =>
        current.map((item) => {
          if (item.id === result.project.id) return result.project;
          if (!stopped.has(item.id)) return item;
          return {
            ...item,
            status: "failed",
            error_message: result.project.error_message || "Stopped by you.",
            stage_label: result.project.stage_label || "Stopped",
          };
        }),
      );
      setSelectedId(result.project.id);
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to stop generation."));
    } finally {
      setPending(false);
    }
  }

  function closeDelete() {
    if (pending) return;
    setDeleting(null);
    setConfirmFailed(false);
  }

  async function confirmDeleteFailed() {
    if (!token) return;
    setError("");
    setPending(true);
    try {
      await api<{ deleted: number }>(endpoints.ai.videoFailed, {
        method: "DELETE",
        token,
      });
      const removed = new Set(videos.filter((item) => item.status === "failed").map((item) => item.id));
      setVideos((current) => current.filter((item) => item.status !== "failed"));
      setSelectedId((current) => (current != null && removed.has(current) ? null : current));
      setConfirmFailed(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete failed videos.");
    } finally {
      setPending(false);
    }
  }

  async function confirmDelete() {
    if (!deleting || !token) return;
    setError("");
    setPending(true);
    try {
      await api(endpoints.ai.videoDetail(deleting.id), {
        method: "DELETE",
        token,
      });
      setVideos((current) => current.filter((item) => item.id !== deleting.id));
      setSelectedId((current) => (current === deleting.id ? null : current));
      setDeleting(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete this video.");
    } finally {
      setPending(false);
    }
  }

  async function download(item: VideoProject) {
    setError("");
    setDownloadingId(item.id);
    try {
      await downloadLibraryVideo(item);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to download this video.");
    } finally {
      setDownloadingId(null);
    }
  }

  return (
    <div>
      <p className="text-xs uppercase tracking-[0.22em] text-gold">Video</p>
      <div className="mt-3 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-serif text-4xl md:text-5xl">Generated videos</h1>
          <p className="mt-4 max-w-2xl text-pretty text-muted">
            Filter the library, open a video in the player, then download the file
            or add an amendment if you want it remade. Name the locale (Cantonese, Mandarin, Hokkien)
            in the box to lock spoken audio.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {library.some((item) => item.status === "failed") ? (
            <button
              type="button"
              disabled={pending}
              onClick={() => {
                setError("");
                setConfirmFailed(true);
              }}
              className="inline-flex h-11 items-center rounded-full border border-[#ffd0e2] px-5 text-sm text-[#b71958] hover:bg-[#fff0f6] disabled:opacity-50"
            >
              Delete failed
            </button>
          ) : null}
          <Link
            href="/brand/studio/bulk"
            className="inline-flex h-11 items-center rounded-full border border-line px-5 text-sm hover:bg-black/5"
          >
            Bulk Studio
          </Link>
          <Link
            href="/brand/studio"
            className="inline-flex h-11 items-center rounded-full bg-gold px-5 text-sm font-medium hover:bg-gold-deep"
          >
            New video
          </Link>
        </div>
      </div>

      {error ? (
        <p className="mt-6 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {error}
        </p>
      ) : null}

      {loading ? (
        <p className="mt-10 text-muted">Loading videos…</p>
      ) : !library.length ? (
        <div className="mt-10 rounded-3xl border border-line bg-card px-6 py-12 text-center">
          <p className="font-serif text-2xl">No videos yet</p>
          <p className="mt-3 text-sm text-muted">Create one in the studio and it will show up here.</p>
          <Link
            href="/brand/studio"
            className="mt-6 inline-flex h-11 items-center rounded-full bg-gold px-5 text-sm font-medium hover:bg-gold-deep"
          >
            Open AI studio
          </Link>
        </div>
      ) : (
        <>
          <section className="mt-8 rounded-3xl border border-line bg-card p-4 md:p-5">
            <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_14rem]">
              <label className="block text-sm">
                Search
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Product name"
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
              <label className="block text-sm">
                Language
                <select
                  value={languageFilter}
                  onChange={(event) => setLanguageFilter(event.target.value)}
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                >
                  <option value="">All languages</option>
                  {languages.map((language) => (
                    <option key={language} value={language}>
                      {languageLabel(language)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {LIBRARY_STATUS_FILTERS.map((option) => {
                const active = statusFilter === option.id;
                const count =
                  option.id === "all"
                    ? library.length
                    : library.filter((item) => matchesLibraryFilter(item, { query: "", status: option.id, language: "" }))
                        .length;
                return (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => setStatusFilter(option.id)}
                    className={`rounded-full px-3 py-1.5 text-xs ${
                      active ? "bg-gold text-white" : "border border-line hover:bg-black/5"
                    }`}
                  >
                    {option.label} · {count}
                  </button>
                );
              })}
            </div>
          </section>

          {selected ? (
            <section className="mt-8 rounded-3xl border border-line bg-card p-5 md:p-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-gold">Display</p>
                  <h2 className="mt-2 font-serif text-3xl">{selected.product_name || "Product video"}</h2>
                </div>
                <StatusBadge item={selected} />
              </div>
              <div className="mt-6 grid gap-8 xl:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
                <div className="mx-auto w-full max-w-xs">
                  {selectedSrc ? (
                    <video
                      key={`${selected.id}-${playingId === selected.id ? "play" : "idle"}`}
                      className="aspect-[9/16] w-full rounded-3xl bg-black shadow-sm"
                      src={selectedSrc}
                      poster={selectedPoster || undefined}
                      controls
                      playsInline
                      autoPlay={playingId === selected.id}
                      onPlay={() => setPlayingId(selected.id)}
                    />
                  ) : selectedPoster ? (
                    <button
                      type="button"
                      onClick={() => playLibraryVideo(selected)}
                      className="relative block w-full overflow-hidden rounded-3xl bg-black shadow-sm"
                    >
                      <img src={selectedPoster} alt="" className="aspect-[9/16] w-full object-cover" />
                      <span className="absolute inset-0 grid place-items-center bg-black/25 text-sm font-medium text-white">
                        Play
                      </span>
                    </button>
                  ) : (
                    <div className="flex aspect-[9/16] items-center justify-center rounded-3xl bg-background text-sm text-muted">
                      {generating ? selected.stage_label || "Creating video" : "Preview will appear here"}
                    </div>
                  )}
                </div>
                <div>
                  <div className="flex flex-wrap gap-2 text-xs text-muted">
                    <span className="rounded-full border border-line px-3 py-1">
                      {languageLabel(selected.language)}
                    </span>
                    {selected.duration_seconds ? (
                      <span className="rounded-full border border-line px-3 py-1">
                        {selected.duration_seconds}s
                      </span>
                    ) : null}
                    {selected.character_config?.character_name ? (
                      <span className="rounded-full border border-line px-3 py-1">
                        {selected.character_config.character_name}
                      </span>
                    ) : null}
                    {whenLabel(selected) ? (
                      <span className="rounded-full border border-line px-3 py-1">{whenLabel(selected)}</span>
                    ) : null}
                  </div>
                  <p className="mt-4 text-sm text-muted">
                    {generating
                      ? `${selected.progress || 0}% complete. This page updates as the job runs.`
                      : regenerationFailureNotice({
                          errorMessage: selected.error_message,
                          scenes: selected.scenes,
                        }).summary ||
                        (selected.error_message
                          ? selected.error_message
                          : "Download the file, or regenerate from the supplied product photos.")}
                  </p>
                  {generating || selected.generation_metrics?.total_generation_ms ? (
                    <GenerationTimer
                      project={selected}
                      running={generating}
                      size="lg"
                      className="mt-4"
                    />
                  ) : null}
                  {selected.status === "failed" && (selected.scenes || []).some((scene) => scene.failure_code) ? (
                    <div className="mt-4 grid gap-3">
                      {(selected.scenes || [])
                        .filter((scene) => scene.failure_code || scene.generation_status === "failed")
                        .map((scene) => {
                          const failure = generationFailureView(scene);
                          return (
                            <div key={scene.id} className="rounded-2xl border border-line bg-background p-4 text-sm">
                              <p className="font-medium">{failure.title}</p>
                              <p className="mt-2">Provider: {failure.provider}</p>
                              {failure.requestId ? <p className="mt-1">Interaction ID: {failure.requestId}</p> : null}
                              {failure.httpStatus ? <p className="mt-1">HTTP status: {failure.httpStatus}</p> : null}
                              <p className="mt-1">Error code: {failure.code}</p>
                              <p className="mt-1">Provider message: {failure.message}</p>
                            </div>
                          );
                        })}
                    </div>
                  ) : null}
                  {generating ? (
                    <div className="mt-5 h-2 overflow-hidden rounded-full bg-black/5">
                      <div
                        className="h-full rounded-full bg-gold"
                        style={{ width: `${Math.max(selected.progress || 8, 8)}%` }}
                      />
                    </div>
                  ) : null}

                  <label className="mt-8 block text-sm font-medium">
                    Amendment
                    <textarea
                      rows={4}
                      value={amendment}
                      onChange={(event) => setAmendment(event.target.value)}
                      placeholder={"Speak Cantonese (粵語), not Mandarin.\nMake every caption the exact spoken sentence."}
                      className="mt-2 w-full rounded-2xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
                      disabled={pending || generating}
                    />
                  </label>
                  <div className="mt-5 flex flex-wrap gap-3">
                    {generating ? (
                      <button
                        type="button"
                        onClick={stopGeneration}
                        disabled={pending}
                        className="inline-flex h-12 items-center rounded-full border border-line px-6 text-sm hover:bg-black/5 disabled:opacity-60"
                      >
                        {pending ? "Stopping…" : "Stop generation"}
                      </button>
                    ) : null}
                    {selectedSrc ? (
                      <button
                        type="button"
                        onClick={() => download(selected)}
                        disabled={downloadingId === selected.id}
                        className="inline-flex h-12 items-center rounded-full bg-gold px-6 text-sm font-medium hover:bg-gold-deep disabled:opacity-60"
                      >
                        {downloadingId === selected.id ? "Downloading…" : "Download"}
                      </button>
                    ) : null}
                    <BulkFromVideoLink
                      item={selected}
                      className="inline-flex h-12 items-center rounded-full border border-line px-6 text-sm hover:bg-black/5"
                    />
                    {(() => {
                      const action = projectPrimaryAction(selected);
                      return (
                        <Link
                          href={action.href}
                          className="inline-flex h-12 items-center rounded-full border border-line px-6 text-sm hover:bg-black/5"
                        >
                          {action.label}
                        </Link>
                      );
                    })()}
                    {selected.status === "failed" ? (
                      <>
                        <Link
                          href={`/brand/studio?project=${selected.id}&step=storyboard`}
                          className="inline-flex h-12 items-center rounded-full border border-line px-6 text-sm hover:bg-black/5"
                        >
                          Edit storyboard
                        </Link>
                        <Link
                          href={`/brand/studio?project=${selected.id}&step=compose`}
                          className="inline-flex h-12 items-center rounded-full border border-line px-6 text-sm hover:bg-black/5"
                        >
                          Back to Brief
                        </Link>
                      </>
                    ) : null}
                    {projectCanApprove(selected) && selected.status !== "approved" && selected.status !== "exported" ? (
                      <Link
                        href={`/brand/studio?project=${selected.id}&step=approve`}
                        className="inline-flex h-12 items-center rounded-full border border-line px-6 text-sm hover:bg-black/5"
                      >
                        Approve
                      </Link>
                    ) : null}
                    <button
                      type="button"
                      disabled={pending || generating || (selected.status === "failed" && sceneRetryBlocked(selected.scenes || []))}
                      onClick={regenerate}
                      className="h-12 rounded-full border border-line px-6 text-sm hover:bg-black/5 disabled:opacity-60"
                    >
                      {pending
                        ? "Starting…"
                        : generating
                          ? "Regenerating…"
                          : selected.status === "failed" && sceneRetryBlocked(selected.scenes || [])
                            ? "Retry blocked"
                            : "Retry"}
                    </button>
                    {selected.status === "failed" && sceneRetryBlocked(selected.scenes || []) ? (
                      <p className="w-full text-sm">This scene cannot be retried until the configuration is fixed.</p>
                    ) : null}
                    <button
                      type="button"
                      disabled={pending}
                      onClick={() => {
                        setError("");
                        setDeleting(selected);
                      }}
                      className="h-12 rounded-full border border-red-200 px-6 text-sm text-red-700 hover:bg-red-50 disabled:opacity-60"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            </section>
          ) : (
            <div className="mt-8 rounded-3xl border border-line bg-card px-6 py-12 text-center text-sm text-muted">
              No videos match these filters.
            </div>
          )}

          <section className="mt-8 overflow-hidden rounded-3xl border border-line bg-card">
            <div className="flex flex-wrap items-end justify-between gap-3 px-5 py-4">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-gold">Library</p>
                <h3 className="mt-1 font-serif text-2xl">All matching videos</h3>
              </div>
              <p className="text-sm text-muted">
                {filtered.length === 0
                  ? "0 videos"
                  : `${rangeStart}–${rangeEnd} of ${filtered.length}`}
              </p>
            </div>
            {visible.length ? (
              <ul className="grid gap-4 px-5 pb-5 sm:grid-cols-2 xl:grid-cols-4">
                {visible.map((item) => {
                  const active = selected?.id === item.id;
                  const src = videoSrc(item);
                  const poster = libraryPosterSrc(item);
                  const playing = playingId === item.id;
                  return (
                    <li key={item.id}>
                      <div
                        className={`overflow-hidden rounded-2xl border ${
                          active ? "border-gold bg-gold/10" : "border-line bg-background"
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => (src ? playLibraryVideo(item) : setSelectedId(item.id))}
                          className="block w-full text-left"
                        >
                          <div className="relative flex aspect-[9/16] items-center justify-center overflow-hidden bg-black text-[10px] text-white/70">
                            {playing && src ? (
                              <video
                                src={src}
                                poster={poster || undefined}
                                className="h-full w-full object-cover"
                                autoPlay
                                playsInline
                                muted
                              />
                            ) : poster ? (
                              <>
                                <img src={poster} alt="" className="h-full w-full object-cover" />
                                {src ? (
                                  <span className="absolute inset-0 grid place-items-center bg-black/20 text-xs font-medium text-white">
                                    Play
                                  </span>
                                ) : null}
                              </>
                            ) : (
                              src ? "Ready · 9:16" : "9:16"
                            )}
                          </div>
                          <div className="p-3">
                            <p className="truncate font-medium">{item.product_name || `Video ${item.id}`}</p>
                            <div className="mt-2 flex flex-wrap items-center gap-2">
                              <StatusBadge item={item} />
                              <span className="text-[11px] text-muted">{languageLabel(item.language)}</span>
                            </div>
                            {whenLabel(item) ? (
                              <p className="mt-2 truncate text-xs text-muted">{whenLabel(item)}</p>
                            ) : null}
                            {ACTIVE_STATUSES.has(item.status) ? (
                              <GenerationTimer
                                project={item}
                                running
                                size="sm"
                                className="mt-2"
                              />
                            ) : null}
                          </div>
                        </button>
                        <div className="grid gap-2 border-t border-line px-3 py-3">
                          <div className="flex gap-2">
                            <button
                              type="button"
                              onClick={() => setSelectedId(item.id)}
                              className="h-9 flex-1 rounded-full border border-line px-3 text-xs hover:bg-black/5"
                            >
                              Open
                            </button>
                            <button
                              type="button"
                              disabled={!src || downloadingId === item.id}
                              onClick={() => download(item)}
                              className="h-9 flex-1 rounded-full bg-gold px-3 text-xs font-medium hover:bg-gold-deep disabled:opacity-50"
                            >
                              {downloadingId === item.id ? "Saving…" : "Download"}
                            </button>
                          </div>
                          <BulkFromVideoLink
                            item={item}
                            className="inline-flex h-9 items-center justify-center rounded-full border border-line px-3 text-xs hover:bg-black/5"
                          />
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="px-5 pb-8 text-sm text-muted">No videos on this page.</p>
            )}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3 text-sm">
              <p className="text-muted">
                {filtered.length === 0
                  ? "0 videos"
                  : `Page ${currentPage} of ${pageCount}`}
              </p>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  disabled={currentPage <= 1}
                  onClick={() => setPage((value) => value - 1)}
                  className="rounded-lg border border-line px-3 py-1.5 disabled:opacity-40"
                >
                  Prev
                </button>
                {libraryPageNumbers(currentPage, pageCount).map((entry, index) =>
                  entry === "ellipsis" ? (
                    <span key={`ellipsis-${index}`} className="px-2 text-muted">
                      …
                    </span>
                  ) : (
                    <button
                      key={entry}
                      type="button"
                      onClick={() => setPage(entry)}
                      className={`min-w-9 rounded-lg px-3 py-1.5 ${
                        entry === currentPage ? "bg-gold text-white" : "border border-line hover:bg-black/5"
                      }`}
                    >
                      {entry}
                    </button>
                  ),
                )}
                <button
                  type="button"
                  disabled={currentPage >= pageCount}
                  onClick={() => setPage((value) => value + 1)}
                  className="rounded-lg border border-line px-3 py-1.5 disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          </section>
        </>
      )}

      {confirmFailed ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            className="absolute inset-0 bg-black/30"
            aria-label="Close"
            onClick={closeDelete}
          />
          <div className="relative w-full max-w-md rounded-2xl border border-line bg-card p-6 shadow-lg">
            <h2 className="font-serif text-2xl">Delete failed videos</h2>
            <p className="mt-3 text-sm text-muted">
              Delete all {library.filter((item) => item.status === "failed").length} failed generations?
              Ready videos stay in the library. This cannot be undone.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                disabled={pending}
                onClick={closeDelete}
                className="inline-flex h-11 items-center rounded-full border border-line px-5 text-sm"
              >
                Keep them
              </button>
              <button
                type="button"
                disabled={pending}
                onClick={confirmDeleteFailed}
                className="inline-flex h-11 items-center rounded-full bg-[#b71958] px-5 text-sm font-medium text-white disabled:opacity-50"
              >
                {pending ? "Deleting…" : "Delete failed"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {deleting ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            className="absolute inset-0 bg-black/30"
            aria-label="Close"
            onClick={closeDelete}
          />
          <div className="relative w-full max-w-md rounded-2xl border border-line bg-card p-6 shadow-lg">
            <h2 className="font-serif text-2xl">Delete video</h2>
            <p className="mt-3 text-sm text-muted">
              Delete{" "}
              <span className="font-medium text-foreground">
                {deleting.product_name || `video ${deleting.id}`}
              </span>
              ? This cannot be undone.
            </p>
            {error ? (
              <p className="mt-4 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </p>
            ) : null}
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={closeDelete}
                disabled={pending}
                className="h-11 rounded-full border border-line px-5 text-sm hover:bg-black/5"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                disabled={pending}
                className="h-11 rounded-full bg-red-600 px-5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
              >
                {pending ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default function VideosPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-full items-center justify-center text-muted">Loading…</div>
      }
    >
      <VideosContent />
    </Suspense>
  );
}
