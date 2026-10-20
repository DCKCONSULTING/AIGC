import { describe, expect, it } from "vitest";

import {
  draftToBriefSeed,
  emptyHomeDraft,
  hasHomeDraft,
  parseHomeDraft,
  studioEntryPath,
} from "./home";

describe("homepage draft", () => {
  it("ignores empty drafts", () => {
    expect(hasHomeDraft(emptyHomeDraft())).toBe(false);
    expect(hasHomeDraft({ ...emptyHomeDraft(), prompt: "  " })).toBe(false);
    expect(hasHomeDraft({ ...emptyHomeDraft(), prompt: "Make a Raya video" })).toBe(true);
  });

  it("parses stored homepage ideas without dropping photos or format", () => {
    const draft = parseHomeDraft(
      JSON.stringify({
        prompt: "Create a 15-second launch video",
        aspect: "9:16",
        duration: 15,
        photos: [{ name: "cup.jpg", type: "image/jpeg", dataUrl: "data:image/jpeg;base64,abc" }],
        savedAt: 1,
      }),
    );
    expect(draft?.prompt).toContain("launch video");
    expect(draft?.photos).toHaveLength(1);
    expect(draft?.duration).toBe(15);
  });

  it("rejects invalid storage and maps a brief seed for studio", () => {
    expect(parseHomeDraft("{not-json")).toBe(null);
    const seed = draftToBriefSeed({
      ...emptyHomeDraft(),
      prompt: "Keep the cup in morning light.\nAdd Bahasa Melayu captions.",
      aspect: "9:16",
      duration: 15,
    });
    expect(seed.platform).toBe("tiktok");
    expect(seed.main_benefit).toContain("Keep the cup");
    expect(seed.must_remain_exact).toContain("product_appearance");
    expect(studioEntryPath()).toBe("/brand/studio?from=home");
  });
});
