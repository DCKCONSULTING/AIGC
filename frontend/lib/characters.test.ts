import { describe, expect, it } from "vitest";

import {
  applyCharacterDefaults,
  characterHasFrontSource,
  characterIsVideoReady,
  characterLibraryMessage,
  characterLibraryPhase,
  characterMasterLabel,
  FRONT_PHOTO_REQUIRED_MESSAGE,
  characterPhotoPersisted,
  characterSaveLabel,
  charactersAfterActingUserChange,
} from "./characters";

describe("character defaults", () => {
  it("loads voice settings for this video without changing the character", () => {
    const character = {
      default_language: "english",
      default_tone: "warm",
      gender: "female" as const,
      default_voice_id: "en-US-Wavenet-F",
      default_voice_provider: "google_tts",
      default_voice_name: "en-US-Wavenet-F",
    };
    const current = {
      language: "conversational_bm",
      style: "bold",
      gender: "male",
      voiceId: "",
      voiceProvider: "",
      voiceName: "",
    };
    const next = applyCharacterDefaults(current, character);
    next.language = "hokkien";
    expect(character.default_language).toBe("english");
    expect(current.language).toBe("conversational_bm");
    expect(next.style).toBe("warm");
    expect(next.voiceId).toBe("en-US-Wavenet-F");
  });

  it("shows a loading library before an empty result", () => {
    expect(characterLibraryPhase({ loading: true, error: "", count: 0 })).toBe("loading");
    expect(characterLibraryMessage("loading")).toBe("Loading characters…");
    expect(characterLibraryPhase({ loading: false, error: "", count: 0 })).toBe("empty");
    expect(characterLibraryMessage("empty")).toContain("No characters yet");
    expect(characterLibraryPhase({ loading: false, error: "Unable to load characters.", count: 0 })).toBe("error");
    expect(characterLibraryMessage("error")).toBe("");
  });

  it("replaces characters when the acting user changes", () => {
    const userA = charactersAfterActingUserChange({
      previousUserId: null,
      nextUserId: 3,
      previousCharacters: [],
      nextCharacters: [{ id: 12, name: "Mike" }],
    });
    expect(userA.map((item) => item.id)).toEqual([12]);
    const cleared = charactersAfterActingUserChange({
      previousUserId: 3,
      nextUserId: 8,
      previousCharacters: userA,
      nextCharacters: null,
    });
    expect(cleared).toEqual([]);
    const userB = charactersAfterActingUserChange({
      previousUserId: 3,
      nextUserId: 8,
      previousCharacters: userA,
      nextCharacters: [{ id: 10, name: "Aisha" }],
    });
    expect(userB.map((item) => item.id)).toEqual([10]);
    expect(userB.some((item) => item.id === 12)).toBe(false);
  });

  it("labels character save without an invented ETA", () => {
    expect(characterSaveLabel("idle", "Create character")).toBe("Create character");
    expect(characterSaveLabel("saving", "Create character")).toBe("Saving character…");
    expect(characterSaveLabel("saved", "Create character")).toBe("Character saved");
    expect(characterSaveLabel("saving", "Create character")).not.toMatch(/30|%/);
  });

  it("keeps the form open when a selected photo is missing from the saved character", () => {
    expect(characterPhotoPersisted({ filesSelected: 1, references: [], previewUrl: "" }).ok).toBe(false);
    expect(characterPhotoPersisted({ filesSelected: 1, references: [{ id: 4 }] }).ok).toBe(true);
    expect(characterPhotoPersisted({ filesSelected: 1, references: [], sourceFrontUrl: "/media/face.png" }).ok).toBe(true);
    expect(characterPhotoPersisted({ filesSelected: 0, references: [] }).ok).toBe(true);
  });

  it("only marks approved masters as ready for Studio video generation", () => {
    expect(characterIsVideoReady({ master_reference_status: "pending", master_reference_approved: false })).toBe(false);
    expect(
      characterIsVideoReady({
        master_reference_status: "ready",
        master_reference_approved: true,
        master_reference_url: "/media/master.png",
      }),
    ).toBe(true);
    expect(characterMasterLabel({ master_reference_status: "processing" })).toBe("Generating…");
    expect(
      characterMasterLabel({
        master_reference_status: "ready",
        master_reference_approved: true,
        master_reference_url: "/media/master.png",
        master_reference_version: 2,
        latest_master_version: 2,
      }),
    ).toBe("Approved (v2)");
    expect(characterMasterLabel({ master_reference_status: "pending", latest_master_version: 1 })).toBe("Ready for approval");
    expect(characterHasFrontSource({ source_front_url: "/media/front.png" })).toBe(true);
    expect(characterHasFrontSource({ references: [{ id: 1, url: "/media/front.png", view_type: "front", sort_order: 0, created_at: "" }] })).toBe(true);
    expect(characterHasFrontSource({ references: [{ id: 1, url: "/media/left.png", view_type: "left", sort_order: 0, created_at: "" }] })).toBe(false);
    expect(FRONT_PHOTO_REQUIRED_MESSAGE).toContain("front-facing photo");
  });
});
