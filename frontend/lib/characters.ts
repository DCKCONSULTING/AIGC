import type { StudioCharacter } from "./api";

export type CharacterVoiceSelection = {
  language: string;
  style: string;
  gender: string;
  voiceId: string;
  voiceProvider: string;
  voiceName: string;
};

export type CharacterLibraryPhase = "loading" | "error" | "empty" | "ready";

export const MASTER_REQUIRED_MESSAGE =
  "This character does not have an approved Master Character Reference. Generate or approve the master character before creating a video.";

export const FRONT_PHOTO_REQUIRED_MESSAGE =
  "A front-facing photo is required to create the Master Character. Please upload one before continuing.";

export function characterLibraryPhase(input: {
  loading: boolean;
  error: string;
  count: number;
}): CharacterLibraryPhase {
  if (input.loading) return "loading";
  if (input.error) return "error";
  if (input.count === 0) return "empty";
  return "ready";
}

export function characterLibraryMessage(phase: CharacterLibraryPhase): string {
  if (phase === "loading") return "Loading characters…";
  if (phase === "empty") return "No characters yet. Create one to reuse across products.";
  return "";
}

export function charactersAfterActingUserChange<T>(input: {
  previousUserId: number | null;
  nextUserId: number | null;
  previousCharacters: T[];
  nextCharacters: T[] | null;
}): T[] {
  if (input.previousUserId !== input.nextUserId) {
    return input.nextCharacters || [];
  }
  return input.nextCharacters === null ? input.previousCharacters : input.nextCharacters;
}

export type CharacterSavePhase = "idle" | "saving" | "saved";

export function characterSaveLabel(phase: CharacterSavePhase, submitLabel: string): string {
  if (phase === "saving") return "Saving character…";
  if (phase === "saved") return "Character saved";
  return submitLabel;
}

export function characterPhotoPersisted(input: {
  filesSelected: number;
  references?: { id?: number }[];
  previewUrl?: string;
  sourceFrontUrl?: string;
}): { ok: boolean; error: string } {
  const hasImage = Boolean((input.references || []).length || input.previewUrl || input.sourceFrontUrl);
  if (input.filesSelected > 0 && !hasImage) {
    return {
      ok: false,
      error: "The reference image was not saved. Please try the upload again.",
    };
  }
  return { ok: true, error: "" };
}

export function characterHasFrontSource(
  character?: Partial<Pick<StudioCharacter, "source_front_url" | "front_source_available" | "references">> | null,
  pendingPhoto?: boolean,
): boolean {
  if (pendingPhoto) return true;
  if (!character) return false;
  if (character.front_source_available) return true;
  if (character.source_front_url) return true;
  return Boolean(character.references?.some((item) => item.view_type === "front" && item.url));
}

export function characterIsVideoReady(
  character?: Pick<StudioCharacter, "master_reference_status" | "master_reference_approved" | "master_reference_url"> | null,
): boolean {
  return Boolean(
    character &&
      character.master_reference_status === "ready" &&
      character.master_reference_approved &&
      character.master_reference_url,
  );
}

export function characterMasterLabel(
  character?: Pick<
    StudioCharacter,
    | "master_reference_status"
    | "master_reference_approved"
    | "master_reference_version"
    | "master_reference_url"
    | "latest_master_version"
  > | null,
): string {
  if (!character) return "Not generated";
  if (character.master_reference_status === "processing") return "Generating…";
  const latest = character.latest_master_version || 0;
  const approved = character.master_reference_version || 0;
  if (characterIsVideoReady(character) && latest <= approved) {
    return `Approved (v${approved || 1})`;
  }
  if (latest > 0) return "Ready for approval";
  if (character.master_reference_status === "failed") return "Failed";
  return "Not generated";
}

export function applyCharacterDefaults(
  current: CharacterVoiceSelection,
  character: Pick<
    StudioCharacter,
    "default_language" | "default_tone" | "gender" | "default_voice_id" | "default_voice_provider" | "default_voice_name"
  >,
): CharacterVoiceSelection {
  return {
    ...current,
    language: character.default_language || current.language,
    style: character.default_tone || current.style,
    gender: character.gender || current.gender,
    voiceId: character.default_voice_id || current.voiceId,
    voiceProvider: character.default_voice_provider || "google_tts",
    voiceName: character.default_voice_name || current.voiceName,
  };
}
