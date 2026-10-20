import { describe, expect, it } from "vitest";

import {
  briefFromProject,
  briefIsReady,
  conceptCreateChecks,
  emptyBrief,
  formatClock,
  sceneLabel,
  canVisitStudioStep,
} from "./director";

describe("director brief helpers", () => {
  it("requires a viewer action, customer, and benefit", () => {
    const brief = emptyBrief();
    expect(briefIsReady(brief)).toBe(false);
    expect(briefIsReady({ ...brief, objective: "buy", customer: "Parents", main_benefit: "Fast meals" })).toBe(
      true,
    );
  });

  it("lists what is still needed before creating concepts", () => {
    const missing = conceptCreateChecks({
      hasProduct: false,
      objective: "",
      customer: "",
      mainBenefit: "",
      generateCharacter: false,
      hasCharacter: false,
      characterReady: false,
    }).filter((item) => !item.ready);
    expect(missing.map((item) => item.id)).toEqual(["product", "objective", "customer", "benefit", "character"]);
    const master = conceptCreateChecks({
      hasProduct: true,
      objective: "buy",
      customer: "Parents",
      mainBenefit: "Fast meals",
      generateCharacter: false,
      hasCharacter: true,
      characterReady: false,
    }).filter((item) => !item.ready);
    expect(master).toHaveLength(1);
    expect(master[0].id).toBe("character");
    expect(master[0].hint).toMatch(/approved master/i);
    expect(
      conceptCreateChecks({
        hasProduct: true,
        objective: "buy",
        customer: "Parents",
        mainBenefit: "Fast meals",
        generateCharacter: true,
        hasCharacter: false,
        characterReady: false,
      }).every((item) => item.ready),
    ).toBe(true);
  });

  it("reads a legacy project as a creative brief", () => {
    const brief = briefFromProject({
      creative_brief: { audience: "Parents", promise: "Hydrating", hook: "Hi" },
      merchant_instructions: "Buat video BM santai.",
      duration_seconds: 45,
      product_snapshot: { price: "39.90" },
    } as never);
    expect(brief.customer).toBe("Parents");
    expect(brief.main_benefit).toBe("Hydrating");
    expect(brief.original_price).toBe("39.90");
  });

  it("formats scene times and statuses for merchants", () => {
    expect(formatClock(75)).toBe("1:15");
    expect(sceneLabel("regenerating")).toBe("Regenerating");
    expect(sceneLabel("failed")).toBe("Failed");
  });

  it("does not open generate until a storyboard exists", () => {
    expect(canVisitStudioStep("generate")).toBe(false);
    expect(canVisitStudioStep("concepts", { creative_directions: [{ title: "UGC" }] } as never)).toBe(true);
    expect(
      canVisitStudioStep("storyboard", {
        selected_concept_id: "ugc",
        scenes: [{ scene_key: "scene-1" }],
      } as never),
    ).toBe(true);
    expect(canVisitStudioStep("review", { status: "draft" } as never)).toBe(false);
    expect(canVisitStudioStep("approve", { status: "ready", preview_url: "https://example.test/v.mp4" } as never)).toBe(
      false,
    );
    expect(canVisitStudioStep("approve", { status: "approved" } as never)).toBe(true);
  });
});
