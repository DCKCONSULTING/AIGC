"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { api, endpoints, type Brand, type StudioCharacter, type VoiceOption } from "@/lib/api";
import {
  characterPhotoPersisted,
  characterSaveLabel,
  characterIsVideoReady,
  characterMasterLabel,
  characterHasFrontSource,
  FRONT_PHOTO_REQUIRED_MESSAGE,
  type CharacterSavePhase,
} from "@/lib/characters";
import { GENDER_OPTIONS, LANGUAGE_OPTIONS, STYLE_OPTIONS, genderLabel, languageLabel, styleLabel } from "@/lib/studio";

export type CharacterDraft = {
  brand: string;
  name: string;
  description: string;
  gender: string;
  appearance_description: string;
  personality_description: string;
  wardrobe_description: string;
  default_language: string;
  default_tone: string;
  default_voice_id: string;
};

export const emptyCharacterDraft = (brand = ""): CharacterDraft => ({
  brand,
  name: "",
  description: "",
  gender: "female",
  appearance_description: "",
  personality_description: "",
  wardrobe_description: "",
  default_language: "conversational_bm",
  default_tone: "warm",
  default_voice_id: "",
});

export function draftFromCharacter(character: StudioCharacter): CharacterDraft {
  return {
    brand: String(character.brand),
    name: character.name,
    description: character.description || "",
    gender: character.gender,
    appearance_description: character.appearance_description || "",
    personality_description: character.personality_description || "",
    wardrobe_description: character.wardrobe_description || "",
    default_language: character.default_language,
    default_tone: character.default_tone,
    default_voice_id: character.default_voice_id || "",
  };
}

export function CharacterForm({
  token,
  brands,
  voices,
  initial,
  characterId,
  existingPreview,
  savedReferenceCount = 0,
  character,
  onSaved,
  submitLabel = "Save character",
}: {
  token: string;
  brands: Brand[];
  voices: VoiceOption[];
  initial: CharacterDraft;
  characterId?: number;
  existingPreview?: string;
  savedReferenceCount?: number;
  character?: StudioCharacter;
  onSaved: (character: StudioCharacter) => void;
  submitLabel?: string;
}) {
  const [draft, setDraft] = useState(initial);
  const [photo, setPhoto] = useState<File | undefined>();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [savePhase, setSavePhase] = useState<CharacterSavePhase>("idle");
  const [record, setRecord] = useState<StudioCharacter | undefined>(character);
  const [masterBusy, setMasterBusy] = useState(false);

  const voiceChoices = useMemo(
    () => voices.filter((item) => item.language === draft.default_language && item.gender === draft.gender),
    [voices, draft.default_language, draft.gender],
  );
  const selectedVoice = voiceChoices.find((item) => item.voice_id === draft.default_voice_id) || voiceChoices[0];
  const blobUrl = useMemo(() => (photo ? URL.createObjectURL(photo) : ""), [photo]);
  const live = record || character;
  const sourcePreview = blobUrl || live?.source_front_url || "";
  const previewUrl = sourcePreview || live?.master_reference_url || live?.latest_master_url || existingPreview || "";
  const MAX_PHOTO_BYTES = 8 * 1024 * 1024;

  useEffect(() => {
    if (character) setRecord(character);
  }, [character]);

  useEffect(() => {
    if (!blobUrl) return;
    return () => URL.revokeObjectURL(blobUrl);
  }, [blobUrl]);

  function patch(next: Partial<CharacterDraft>) {
    setDraft((current) => ({ ...current, ...next }));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!draft.name.trim()) {
      setError("Character name is required.");
      return;
    }
    if (!draft.gender) {
      setError("Choose Female, Male, or Neutral.");
      return;
    }
    if (photo && photo.size > MAX_PHOTO_BYTES) {
      setError("Each photo must be 8 MB or smaller.");
      return;
    }
    if (!draft.appearance_description.trim() && !characterHasFrontSource(live, Boolean(photo))) {
      setError("Add an appearance description or one front-facing photo.");
      return;
    }
    setPending(true);
    setSavePhase("saving");
    setError("");
    try {
      const body = new FormData();
      body.append("brand", draft.brand || String(brands[0]?.id || ""));
      body.append("name", draft.name.trim());
      body.append("description", draft.description);
      body.append("gender", draft.gender);
      body.append("appearance_description", draft.appearance_description);
      body.append("personality_description", draft.personality_description);
      body.append("wardrobe_description", draft.wardrobe_description);
      body.append("default_language", draft.default_language);
      body.append("default_tone", draft.default_tone);
      if (selectedVoice?.voice_id) body.append("default_voice_id", selectedVoice.voice_id);
      if (photo) body.append("reference_front", photo);
      body.append("reference_count", photo ? "1" : "0");
      if (process.env.NODE_ENV === "development") {
        console.info("[character] upload", { front: Boolean(photo), count: photo ? 1 : 0 });
      }
      const saved = await api<StudioCharacter>(
        characterId ? endpoints.ai.characterDetail(characterId) : endpoints.ai.characters,
        { method: characterId ? "PATCH" : "POST", token, body },
      );
      const persisted = characterPhotoPersisted({
        filesSelected: photo ? 1 : 0,
        references: saved.references,
        previewUrl: saved.preview_url,
        sourceFrontUrl: saved.source_front_url,
      });
      if (!persisted.ok) {
        throw new Error(persisted.error);
      }
      setSavePhase("saved");
      setRecord(saved);
      setPhoto(undefined);
      onSaved(saved);
    } catch (err) {
      setSavePhase("idle");
      setError(err instanceof Error ? err.message : "Unable to save this character.");
    } finally {
      setPending(false);
    }
  }

  async function runMaster(mode: "generate" | "regenerate") {
    const id = live?.id || characterId;
    if (!id) {
      setError("Save the character first, then generate the master character.");
      return;
    }
    setMasterBusy(true);
    setError("");
    try {
      const saved = await api<StudioCharacter>(endpoints.ai.characterMasterReference(id), {
        method: "POST",
        token,
        body: JSON.stringify({ regenerate: mode === "regenerate" }),
      });
      setRecord(saved);
      onSaved(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to generate the master character.");
    } finally {
      setMasterBusy(false);
    }
  }

  async function approveMaster() {
    const id = live?.id || characterId;
    if (!id) return;
    setMasterBusy(true);
    setError("");
    try {
      const saved = await api<StudioCharacter>(endpoints.ai.characterMasterApprove(id), {
        method: "POST",
        token,
        body: JSON.stringify({}),
      });
      setRecord(saved);
      onSaved(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to approve the master character.");
    } finally {
      setMasterBusy(false);
    }
  }

  const hasFrontSource = characterHasFrontSource(live, Boolean(photo));
  const masterPreview = live?.latest_master_url || live?.master_reference_url || "";
  const canGenerateMaster = Boolean((live?.id || characterId) && hasFrontSource);
  const latestVersion = live?.latest_master_version || 0;
  const approvedVersion = live?.master_reference_version || 0;
  const awaitingApprove = Boolean(masterPreview && (latestVersion > approvedVersion || !characterIsVideoReady(live)));
  const displayMasterVersion = latestVersion || approvedVersion;

  return (
    <form onSubmit={onSubmit} className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
      <div className="grid gap-6">
        {error ? (
          <p className="rounded-xl border border-[#ffd0e2] bg-[#fff0f6] px-4 py-3 text-sm" role="alert">
            {error}
          </p>
        ) : null}
        <section className="rounded-2xl border border-line bg-card p-5">
          <h2 className="font-serif text-2xl">Basic information</h2>
          <div className="mt-4 grid gap-4">
            {brands.length > 1 ? (
              <label className="block text-sm">
                Brand
                <select
                  value={draft.brand}
                  onChange={(event) => patch({ brand: event.target.value })}
                  className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                >
                  {brands.map((brand) => (
                    <option key={brand.id} value={brand.id}>
                      {brand.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            <label className="block text-sm">
              Character name
              <input
                value={draft.name}
                onChange={(event) => patch({ name: event.target.value })}
                placeholder="Sarah"
                className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              />
            </label>
            <label className="block text-sm">
              Description
              <textarea
                rows={3}
                value={draft.description}
                onChange={(event) => patch({ description: event.target.value })}
                placeholder="Friendly Malaysian business woman who explains products naturally and confidently."
                className="mt-2 w-full rounded-2xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
              />
            </label>
            <label className="block text-sm">
              Gender
              <select
                value={draft.gender}
                onChange={(event) => patch({ gender: event.target.value, default_voice_id: "" })}
                className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              >
                {GENDER_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </section>

        <div className="grid items-start gap-4 md:grid-cols-2">
          <section className="rounded-2xl border border-line bg-card p-4">
            <h2 className="font-serif text-xl">Character photo</h2>
            <p className="mt-1 text-xs text-muted">
              One clear front-facing photo. This is the identity source.
            </p>
            <label className="mt-3 block text-sm">
              Front-facing photo
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="mt-2 w-full text-sm"
                onChange={(event) => setPhoto(event.target.files?.[0])}
              />
            </label>
            <p className="mt-1 text-xs text-muted">JPG, PNG, or WebP. Max 8 MB.</p>
            <div className="mt-3 mx-auto w-full max-w-[11rem] overflow-hidden rounded-lg bg-[#f4f7fb]">
              {sourcePreview ? (
                <img src={sourcePreview} alt="Front-facing source photo" className="aspect-[3/4] w-full object-cover" />
              ) : (
                <div className="grid aspect-[3/4] place-items-center px-3 text-center text-xs text-muted">No photo yet</div>
              )}
            </div>
            {hasFrontSource && !photo ? (
              <p className="mt-2 text-xs text-muted">Original source photo is preserved.</p>
            ) : null}
          </section>

          {live?.id || characterId ? (
            <section className="rounded-2xl border border-line bg-card p-4">
              <h2 className="font-serif text-xl">Master Character</h2>
              <p className="mt-1 text-xs text-muted">Status: {characterMasterLabel(live)}</p>
              {displayMasterVersion ? <p className="text-xs text-muted">Version v{displayMasterVersion}</p> : null}
              <div className="mt-3 mx-auto w-full max-w-[11rem] overflow-hidden rounded-lg bg-[#f4f7fb]">
                {masterBusy ? (
                  <div className="grid aspect-[3/4] place-items-center px-3 text-center text-xs text-muted">
                    Generating…
                  </div>
                ) : masterPreview ? (
                  <img src={masterPreview} alt="Master character reference" className="aspect-[3/4] w-full object-cover" />
                ) : (
                  <div className="grid aspect-[3/4] place-items-center px-3 text-center text-xs text-muted">
                    {hasFrontSource ? "Not generated yet" : FRONT_PHOTO_REQUIRED_MESSAGE}
                  </div>
                )}
              </div>
              <p className="mt-2 text-xs text-muted">Visual identity reference for Studio videos.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  type="button"
                  disabled={masterBusy || !canGenerateMaster}
                  onClick={() => runMaster(masterPreview ? "regenerate" : "generate")}
                  className="h-9 rounded-full border border-line px-3 text-xs font-medium hover:bg-background disabled:opacity-60"
                >
                  {masterBusy ? "Generating…" : masterPreview ? "Regenerate" : "Generate"}
                </button>
                {awaitingApprove ? (
                  <button
                    type="button"
                    disabled={masterBusy}
                    onClick={approveMaster}
                    className="h-9 rounded-full bg-gold px-3 text-xs font-medium hover:bg-gold-deep disabled:opacity-60"
                  >
                    Approve
                  </button>
                ) : null}
              </div>
              {characterIsVideoReady(live) ? (
                <p className="mt-2 text-xs text-muted">Ready for Studio.</p>
              ) : (
                <p className="mt-2 text-xs text-muted">Approve before using in a new Studio video.</p>
              )}
            </section>
          ) : (
            <p className="rounded-2xl border border-line bg-card px-4 py-4 text-sm text-muted">
              Save the character with a front photo, then generate and approve the Master Character.
            </p>
          )}
        </div>

        <section className="rounded-2xl border border-line bg-card p-5">
          <h2 className="font-serif text-2xl">Appearance</h2>
          <p className="mt-2 text-sm text-muted">Optional text fields. The front-facing photo is the primary visual identity.</p>
          <label className="mt-4 block text-sm">
            Appearance description
            <textarea
              rows={3}
              value={draft.appearance_description}
              onChange={(event) => patch({ appearance_description: event.target.value })}
              placeholder="Malaysian Chinese woman, approximately 30 years old, shoulder-length black hair, light blue blazer."
              className="mt-2 w-full rounded-2xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
            />
          </label>
          <div className="mt-4 grid gap-4">
            <label className="block text-sm">
              Personality
              <input
                value={draft.personality_description}
                onChange={(event) => patch({ personality_description: event.target.value })}
                className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              />
            </label>
            <label className="block text-sm">
              Wardrobe
              <input
                value={draft.wardrobe_description}
                onChange={(event) => patch({ wardrobe_description: event.target.value })}
                className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              />
            </label>
          </div>
        </section>

        <section className="rounded-2xl border border-line bg-card p-5">
          <h2 className="font-serif text-2xl">Preferred voice</h2>
          <p className="mt-2 text-sm text-muted">
            These are preferences for Studio video generation. Spoken audio is generated with the video. The
            selected voice is not a separate TTS audio track.
          </p>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <label className="block text-sm">
              Default language
              <select
                value={draft.default_language}
                onChange={(event) => patch({ default_language: event.target.value, default_voice_id: "" })}
                className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              >
                {LANGUAGE_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id} title={option.hint}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              Default tone
              <select
                value={draft.default_tone}
                onChange={(event) => patch({ default_tone: event.target.value })}
                className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              >
                {STYLE_OPTIONS.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm md:col-span-2">
              Preferred voice
              <select
                value={selectedVoice?.voice_id || ""}
                onChange={(event) => patch({ default_voice_id: event.target.value })}
                className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              >
                {voiceChoices.map((option) => (
                  <option key={`${option.language}-${option.gender}-${option.voice_id}`} value={option.voice_id}>
                    {option.voice_name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </section>

        <button
          type="submit"
          disabled={pending}
          className="h-11 w-fit rounded-full bg-gold px-5 text-sm font-medium hover:bg-gold-deep disabled:opacity-60"
        >
          {characterSaveLabel(savePhase, submitLabel)}
        </button>
      </div>

      <aside className="rounded-2xl border border-line bg-card p-5 lg:sticky lg:top-6">
        <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-primary">Character preview</p>
        <div className="mt-4 overflow-hidden rounded-xl bg-[#f4f7fb]">
          {previewUrl ? (
            <img src={previewUrl} alt="" className="aspect-[3/4] w-full object-cover" />
          ) : (
            <div className="grid aspect-[3/4] place-items-center px-4 text-center text-sm text-muted">
              {savedReferenceCount
                ? "This photo file is missing. Upload it again."
                : "No photo yet"}
            </div>
          )}
        </div>
        <h3 className="mt-4 font-serif text-2xl">{draft.name || "Untitled"}</h3>
        <p className="mt-2 text-sm text-muted">
          {genderLabel(draft.gender)} · {languageLabel(draft.default_language)} · {styleLabel(draft.default_tone)}
        </p>
        {selectedVoice ? <p className="mt-1 text-sm">{selectedVoice.voice_name}</p> : null}
        <p className="mt-3 text-sm leading-6">
          {draft.appearance_description || draft.description || "Appearance and description show here."}
        </p>
      </aside>
    </form>
  );
}
