import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const root = join(__dirname, "..");

describe("Studio UI regressions", () => {
  it("Concepts tab exposes Generate and Fast generation actions", () => {
    const source = readFileSync(join(root, "components/studio/ConceptCards.tsx"), "utf8");
    expect(source).toContain("Generate ${videoCount} video");
    expect(source).toContain("Fast generation");
    expect(source).toContain("onBulkGenerateFast");
    expect(source).toContain("pendingFast");
  });

  it("Review tab no longer renders the SceneStrip min-w-0 section", () => {
    const review = readFileSync(join(root, "components/studio/VideoReview.tsx"), "utf8");
    expect(review).not.toContain("SceneStrip");
    expect(review).not.toMatch(/className=\"min-w-0\"/);
    expect(review).toContain("Review video");
    expect(review).toContain("Approve video");
    expect(review).toContain("AmendmentAssistant");
  });

  it("Generate tab no longer renders the SceneStrip min-w-0 section", () => {
    const progress = readFileSync(join(root, "components/studio/GenerationProgress.tsx"), "utf8");
    expect(progress).not.toContain("SceneStrip");
    expect(progress).not.toContain("lg:col-span-2");
    expect(progress).toContain("Generation failed");
    expect(progress).toContain("VideoStage");
  });

  it("Studio page wires Fast generation to Seedance 2.0 Fast model id", () => {
    const page = readFileSync(join(root, "app/brand/(workspace)/studio/page.tsx"), "utf8");
    expect(page).toContain("onBulkGenerateFast");
    expect(page).toContain("dreamina-seedance-2-0-fast-260128");
    expect(page).toContain("seedance_model");
  });
});
