"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, endpoints, type StudioCharacter, type VideoProject } from "@/lib/api";
import { characterIsVideoReady, characterLibraryMessage, characterLibraryPhase, characterMasterLabel } from "@/lib/characters";
import { genderLabel, languageLabel, styleLabel } from "@/lib/studio";
import { useAuth } from "@/lib/auth";

export default function CharactersPage() {
  const { token, actingAccount } = useAuth();
  const actingUserId = actingAccount?.userId ?? null;
  const [characters, setCharacters] = useState<StudioCharacter[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [usage, setUsage] = useState<Record<number, VideoProject[]>>({});

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    setCharacters([]);
    setUsage({});
    api<StudioCharacter[]>(endpoints.ai.charactersQuery(showArchived), { token })
      .then((rows) => {
        if (cancelled) return;
        setCharacters(rows);
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setCharacters([]);
        setError(err instanceof Error ? err.message : "Unable to load characters.");
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token, showArchived, actingUserId]);

  async function run(id: number, path: string, method: string, success: string) {
    if (!token) return;
    setPendingId(id);
    setError("");
    try {
      await api(path, { method, token, body: method === "DELETE" ? undefined : "{}" });
      setNote(success);
      setLoading(true);
      const rows = await api<StudioCharacter[]>(endpoints.ai.charactersQuery(showArchived), { token });
      setCharacters(rows);
      setLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update this character.");
    } finally {
      setPendingId(null);
      setLoading(false);
    }
  }

  async function toggleUsage(character: StudioCharacter) {
    if (!token) return;
    if (usage[character.id]) {
      setUsage((current) => {
        const next = { ...current };
        delete next[character.id];
        return next;
      });
      return;
    }
    const rows = await api<VideoProject[]>(endpoints.ai.characterVideos(character.id), { token });
    setUsage((current) => ({ ...current, [character.id]: rows }));
  }

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-serif text-4xl">Characters</h1>
          <p className="mt-3 max-w-2xl text-muted">
            Create reusable characters for your videos. Characters can be reused across products and productions.
          </p>
        </div>
        <Link
          href="/brand/characters/new"
          className="inline-flex h-11 items-center rounded-full bg-gold px-5 text-sm font-medium hover:bg-gold-deep"
        >
          + Create Character
        </Link>
      </div>

      <label className="mt-6 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={showArchived}
          onChange={(event) => setShowArchived(event.target.checked)}
        />
        Show archived
      </label>

      {error ? (
        <p className="mt-4 rounded-xl border border-[#ffd0e2] bg-[#fff0f6] px-4 py-3 text-sm" role="alert">
          {error}
        </p>
      ) : null}
      {note ? <p className="mt-4 text-sm text-muted">{note}</p> : null}

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {characters.map((character) => (
          <article key={character.id} className="rounded-2xl border border-line bg-card p-4">
            <div className="flex gap-4">
              {character.preview_url ? (
                <img src={character.preview_url} alt="" className="h-24 w-20 rounded-xl object-cover" />
              ) : (
                <div className="grid h-24 w-20 place-items-center rounded-xl bg-[#f4f7fb] text-xs text-muted">
                  No photo
                </div>
              )}
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-3">
                  <h2 className="font-serif text-2xl">{character.name}</h2>
                  <span className="rounded-full border border-line px-2 py-1 text-[11px] uppercase tracking-wide text-muted">
                    {character.status}
                  </span>
                </div>
                <p className="mt-1 text-sm text-muted">
                  {genderLabel(character.gender)} · {languageLabel(character.default_language)} ·{" "}
                  Preferred voice {character.default_voice_name || "not set"} · {styleLabel(character.default_tone)}
                </p>
                {character.description ? <p className="mt-2 line-clamp-2 text-sm">{character.description}</p> : null}
                <p className="mt-2 text-xs text-muted">{characterMasterLabel(character)}</p>
                <p className="mt-2 text-xs text-muted">
                  <button type="button" className="underline" onClick={() => toggleUsage(character)}>
                    Used in {character.video_count} video{character.video_count === 1 ? "" : "s"}
                  </button>
                  {" · "}
                  {new Date(character.created_at).toLocaleDateString()}
                </p>
              </div>
            </div>
            {usage[character.id] ? (
              <ul className="mt-3 grid gap-1 text-sm">
                {usage[character.id].length ? (
                  usage[character.id].map((video) => (
                    <li key={video.id}>
                      <Link href="/brand/studio" className="underline">
                        {video.product_name} · {video.status}
                      </Link>
                    </li>
                  ))
                ) : (
                  <li className="text-muted">No productions yet.</li>
                )}
              </ul>
            ) : null}
            <div className="mt-4 flex flex-wrap gap-2">
              <Link
                href={characterIsVideoReady(character) ? `/brand/studio?character=${character.id}` : `/brand/characters/${character.id}`}
                className="inline-flex h-9 items-center rounded-full bg-primary px-3 text-xs font-medium text-white"
              >
                {characterIsVideoReady(character) ? "Use in Video" : "Generate Master"}
              </Link>
              <Link
                href={`/brand/characters/${character.id}`}
                className="inline-flex h-9 items-center rounded-full border border-line px-3 text-xs"
              >
                Edit
              </Link>
              <button
                type="button"
                disabled={pendingId === character.id}
                className="h-9 rounded-full border border-line px-3 text-xs"
                onClick={() => run(character.id, endpoints.ai.characterDuplicate(character.id), "POST", `Duplicated ${character.name}.`)}
              >
                Duplicate
              </button>
              {character.status === "archived" ? (
                <button
                  type="button"
                  disabled={pendingId === character.id}
                  className="h-9 rounded-full border border-line px-3 text-xs"
                  onClick={() => run(character.id, endpoints.ai.characterRestore(character.id), "POST", `${character.name} restored.`)}
                >
                  Restore
                </button>
              ) : (
                <button
                  type="button"
                  disabled={pendingId === character.id}
                  className="h-9 rounded-full border border-line px-3 text-xs"
                  onClick={() => run(character.id, endpoints.ai.characterArchive(character.id), "POST", `${character.name} archived.`)}
                >
                  Archive
                </button>
              )}
              <button
                type="button"
                disabled={pendingId === character.id}
                className="h-9 rounded-full border border-line px-3 text-xs"
                onClick={() => {
                  if (window.confirm(`Delete ${character.name}? Archived characters stay available to old videos.`)) {
                    run(character.id, endpoints.ai.characterDetail(character.id), "DELETE", `${character.name} deleted.`);
                  }
                }}
              >
                Delete
              </button>
            </div>
          </article>
        ))}
      </div>
      {characterLibraryMessage(characterLibraryPhase({ loading, error, count: characters.length })) ? (
        <p className="mt-8 text-sm text-muted">
          {characterLibraryMessage(characterLibraryPhase({ loading, error, count: characters.length }))}
        </p>
      ) : null}
    </div>
  );
}
