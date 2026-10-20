import { describe, expect, it } from "vitest";

import { endpoints } from "./api";
import { BRAND_NAV_GROUPS, isBrandNavActive } from "./brand";
import {
  BULK_MODES,
  acceptedReferenceVideo,
  bulkProgress,
  bulkStepForStatus,
  bulkFromLibraryHref,
  canGeneratePlan,
  canUseLibraryVideoForBulk,
  configureFields,
  isReferenceMode,
  itemStatusLabel,
  parseBulkCount,
  planRows,
  reviewHref,
} from "./bulk-studio";

describe("bulk studio", () => {
  it("exposes four modes and keeps single studio separate", () => {
    expect(BULK_MODES.map((item) => item.id)).toEqual([
      "character",
      "product",
      "existing_video",
      "reference_location",
      "reference_character",
    ]);
    expect(endpoints.ai.bulkVideos).toContain("/api/ai/bulk-video/");
    expect(endpoints.ai.videoProjectGenerate(3)).toContain("/api/ai/video/3/generate/");
    expect(BRAND_NAV_GROUPS[0].links.map((item) => item.href)).toEqual([
      "/brand/studio",
      "/brand/studio/bulk",
      "/brand/videos",
    ]);
    expect(isBrandNavActive("/brand/studio", "/brand/studio")).toBe(true);
    expect(isBrandNavActive("/brand/studio/bulk", "/brand/studio")).toBe(false);
  });

  it("shows the right configure fields for each mode", () => {
    expect(configureFields("character")).toEqual({
      needsCharacter: true,
      needsCharacters: false,
      needsReference: false,
      needsSourceVideo: false,
      productRequired: true,
      countEditable: true,
    });
    expect(configureFields("product").needsCharacter).toBe(false);
    expect(configureFields("reference_location").needsReference).toBe(true);
    expect(configureFields("reference_character")).toMatchObject({
      needsCharacters: true,
      needsReference: true,
      countEditable: false,
    });
    expect(isReferenceMode("reference_location")).toBe(true);
    expect(canGeneratePlan({ mode: "character", productId: 1 })).toBe(false);
    expect(canGeneratePlan({ mode: "character", productId: 1, characterId: 9 })).toBe(true);
    expect(canGeneratePlan({ mode: "reference_location", productId: 1, hasReference: true })).toBe(true);
    expect(acceptedReferenceVideo({ name: "ref.mp4", type: "video/mp4" } as File)).toBe(true);
    expect(acceptedReferenceVideo({ name: "notes.txt", type: "text/plain" } as File)).toBe(false);
    expect(parseBulkCount("7")).toBe(7);
    expect(parseBulkCount("")).toBe(10);
    expect(parseBulkCount("0")).toBe(1);
    expect(parseBulkCount("99")).toBe(10);
  });

  it("edits the plan and reports progress without fake percentages", () => {
    expect(bulkStepForStatus("draft")).toBe("configure");
    expect(bulkStepForStatus("plan_ready")).toBe("plan");
    expect(bulkStepForStatus("generating")).toBe("generate");
    const batch = {
      generation_plan: [
        { sequence: 1, title: "Morning", location: "bathroom" },
        { sequence: 2, title: "Cafe", location: "cafe" },
      ],
      items: [
        {
          id: 1,
          sequence: 1,
          title: "Morning",
          variation_config: { location: "bathroom" },
          video_project: { id: 11, status: "ready_for_review", progress: 100, stage_label: "Ready", error_message: "", preview_url: "/a.mp4", product_name: "Serum" },
          status: "completed",
          error_message: "",
        },
        {
          id: 2,
          sequence: 2,
          title: "Cafe",
          variation_config: { location: "cafe" },
          video_project: { id: 12, status: "generating_video", progress: 64, stage_label: "Creating scenes", error_message: "", preview_url: "", product_name: "Serum" },
          status: "generating",
          error_message: "",
        },
        {
          id: 3,
          sequence: 3,
          title: "Garden",
          variation_config: {},
          video_project: null,
          status: "failed",
          error_message: "Omni rejected this scene.",
        },
      ],
      requested_count: 3,
    } as const;
    expect(planRows(batch as never)).toHaveLength(2);
    expect(bulkProgress(batch as never)).toEqual({
      total: 3,
      completed: 1,
      failed: 1,
      generating: 1,
      percent: 33,
    });
    expect(itemStatusLabel(batch.items[1] as never)).toBe("Creating scenes");
    expect(itemStatusLabel(batch.items[2] as never)).toBe("Omni rejected this scene.");
    expect(reviewHref(11)).toBe("/brand/studio?project=11&step=review");
    expect(canUseLibraryVideoForBulk({ preview_url: "/media/a.mp4" })).toBe(true);
    expect(canUseLibraryVideoForBulk({ preview_url: "" })).toBe(false);
    expect(bulkFromLibraryHref({ id: 44 })).toBe("/brand/studio/bulk?source=44");
  });
});
