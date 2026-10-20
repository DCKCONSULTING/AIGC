import { describe, expect, it } from "vitest";

import { flattenErrors } from "./api";
import {
  LANGUAGE_OPTIONS,
  STYLE_OPTIONS,
  nextStep,
  previousStep,
  reviewStepForStatus,
  asStringList,
  composeInstructions,
  instructionText,
  historyKind,
  historyLabel,
  isLibraryVideo,
  libraryDownloadName,
  libraryPosterSrc,
  libraryPageCount,
  libraryPageItems,
  libraryPageNumbers,
  libraryStatusGroup,
  libraryVideoSrc,
  matchesLibraryFilter,
  merchantError,
  PROVIDER_STATUS_UNAVAILABLE,
  regenerationFailureNotice,
  merchantQaDetail,
  pipelineStageLabel,
  missingEssentials,
  progressStepIndex,
  productionBarWidth,
  productionPhase,
  generationFormatNote,
  formatGenerationClock,
  generationElapsedMs,
  generationStartedAtMs,
  confidenceLabel,
  qaCardDetail,
  qaIncomplete,
  qaLayerSummary,
  qaNeedsRerun,
  qaStatusLabel,
  releaseBlockingIssues,
  seriousQaIssues,
  videoCheckSummary,
  visualQaRollup,
  bulkCreationState,
  expandStudioBulkJobs,
  generationFailureView,
  approvalBlockSummary,
  identityPassed,
  narrationPassed,
  projectCanApprove,
  sceneGateFailures,
  projectPrimaryAction,
  sceneCountForDuration,
  sceneRetryBlocked,
} from "./studio";

describe("studio workflow", () => {
  it("moves through the studio steps", () => {
    expect(nextStep("compose")).toBe("concepts");
    expect(previousStep("generate")).toBe("storyboard");
    expect(nextStep("concepts")).toBe("storyboard");
    expect(nextStep("storyboard")).toBe("generate");
    expect(nextStep("generate")).toBe("review");
    expect(nextStep("review")).toBe("approve");
    expect(LANGUAGE_OPTIONS.every((option) => !/gemini|veo|nano|seedance/i.test(option.label))).toBe(
      true,
    );
    expect(LANGUAGE_OPTIONS.map((option) => option.id)).toEqual(
      expect.arrayContaining(["english", "chinese", "cantonese", "hokkien"]),
    );
    expect(LANGUAGE_OPTIONS.find((option) => option.id === "chinese")?.label).toMatch(/Mandarin/i);
    expect(LANGUAGE_OPTIONS.find((option) => option.id === "cantonese")?.label).toMatch(/Cantonese/i);
    expect(LANGUAGE_OPTIONS.find((option) => option.id === "hokkien")?.label).toMatch(/Hokkien/i);
    expect(STYLE_OPTIONS.every((option) => !/warm|bold|calm|luxury/i.test(option.label))).toBe(
      true,
    );
  });

  it("resumes the right review step from generation status", () => {
    expect(reviewStepForStatus("generating_video")).toBe("generate");
    expect(reviewStepForStatus("generating")).toBe("generate");
    expect(reviewStepForStatus("qa_running")).toBe("generate");
    expect(reviewStepForStatus("ready")).toBe("review");
    expect(reviewStepForStatus("ready_for_review")).toBe("review");
    expect(reviewStepForStatus("approved")).toBe("approve");
  });

  it("maps job status to human progress steps", () => {
    expect(progressStepIndex("analyzing")).toBe(0);
    expect(progressStepIndex("script_ready")).toBe(1);
    expect(progressStepIndex("generating_video")).toBe(3);
    expect(progressStepIndex("qa_running")).toBe(5);
  });

  it("maps backend status to honest production labels", () => {
    expect(productionPhase(null).label).toBe("Ready to generate");
    expect(productionPhase({ status: "script_ready" }).label).toBe("Preparing story");
    expect(productionPhase({ status: "generating_video", scenes: [{ scene_status: "generating", order: 4, title: "Reveal" }] }).label).toBe(
      "Generating video",
    );
    expect(productionPhase({ status: "qa_running" }).label).toBe("Running visual checks");
    expect(productionPhase({ status: "failed", error_message: "timeout" }).label).toBe(
      "Video generation failed",
    );
    expect(productionPhase({ status: "approved" }).key).toBe("approved");
    expect(productionPhase({ status: "exported" }).label).not.toBe("Published");
    const withCharacter = productionPhase({
      status: "draft",
      character_name: "Sarah",
      voice_summary: "English / Friendly / Female",
    });
    expect(withCharacter.mike).toContain("Voice preference:");
    expect(withCharacter.mike).not.toContain("Voice verified");
    expect(
      productionPhase({
        status: "ready_for_review",
        preview_url: "/media/x.mp4",
        qa_results: {
          checks: [
            {
              name: "product_visual_consistency",
              status: "not_checked",
              detail: "Original product photos were not compared with the generated video.",
            },
          ],
        },
      }).mike,
    ).toMatch(/blocked|checks complete/i);
    expect(productionBarWidth("generating_video", 0)).toBeGreaterThan(0);
    expect(productionBarWidth("generating_video", 42)).toBe(42);
    expect(generationFormatNote()).toMatch(/9:16/);
  });

  it("expands bulk studio jobs across stories, characters, gender, and duration", () => {
    const preview = expandStudioBulkJobs({
      conceptIds: ["ugc", "demo"],
      characterIds: [12],
      generateCharacter: true,
      genderMode: "mix",
      durationMode: "mix",
      count: 4,
    });
    expect(preview.error).toBe("");
    expect(preview.combinationCount).toBe(4);
    expect(preview.jobs).toHaveLength(4);
    expect(preview.jobs.map((job) => job.concept_id)).toEqual(["ugc", "ugc", "demo", "demo"]);
    expect(preview.jobs.map((job) => job.generate_character)).toEqual([false, true, false, true]);
    expect(preview.jobs.map((job) => job.gender)).toEqual(["female", "male", "female", "male"]);
    expect(preview.jobs.map((job) => job.duration)).toEqual([15, 30, 45, 60]);
    const covering = expandStudioBulkJobs({
      conceptIds: ["ugc", "demo", "hero"],
      generateCharacter: true,
      count: 1,
    });
    expect(covering.error).toBe("");
    expect(covering.jobs).toHaveLength(3);
    expect(covering.jobs.map((job) => job.concept_id).sort()).toEqual(["demo", "hero", "ugc"]);
    expect(expandStudioBulkJobs({ conceptIds: ["ugc"], generateCharacter: false }).error).toMatch(/character/i);
    expect(expandStudioBulkJobs({ conceptIds: ["ugc"], generateCharacter: true, count: 11 }).error).toMatch(/10/);
  });

  it("formats a live generation clock", () => {
    expect(formatGenerationClock(0)).toBe("0:00");
    expect(formatGenerationClock(4000)).toBe("0:04");
    expect(formatGenerationClock(125_000)).toBe("2:05");
    expect(formatGenerationClock(3_661_000)).toBe("1:01:01");
  });

  it("reads elapsed time from generation metrics and a live start", () => {
    const started = Date.parse("2026-10-02T08:00:00.000Z");
    expect(
      generationStartedAtMs({
        generation_metrics: { started_at: "2026-10-02T08:00:00.000Z" },
      }),
    ).toBe(started);
    expect(
      generationElapsedMs(
        { generation_metrics: { started_at: "2026-10-02T08:00:00.000Z" } },
        Date.parse("2026-10-02T08:03:20.000Z"),
        true,
      ),
    ).toBe(200_000);
    expect(
      generationElapsedMs(
        { generation_metrics: { total_generation_ms: 412_000 } },
        Date.parse("2026-10-02T08:10:00.000Z"),
        false,
      ),
    ).toBe(412_000);
    expect(
      generationElapsedMs(
        {
          generation_metrics: {
            started_at: "2026-10-02T07:00:00.000Z",
            completed_at: "2026-10-02T07:10:00.000Z",
            total_generation_ms: 600_000,
          },
        },
        Date.parse("2026-10-02T08:03:00.000Z"),
        true,
        Date.parse("2026-10-02T08:00:00.000Z"),
      ),
    ).toBe(180_000);
  });

  it("parses merchant lists", () => {
    expect(asStringList("30ml, 50ml")).toEqual(["30ml", "50ml"]);
  });

  it("flags missing product essentials in plain language", () => {
    expect(
      missingEssentials({
        name: "Serum",
        description: "",
        price: "39.90",
        variants: "",
        dimensions: "",
        materials: "glass",
      }),
    ).toEqual(["variant (size or type)", "key facts about the product"]);
  });

  it("hides provider names from merchant errors", () => {
    expect(merchantError("Seedance is not configured.")).toBe(
      "We couldn't finish this just now. Please try again.",
    );
    expect(
      merchantError("Veo quota exceeded. Please retry in 1h.", "RATE_LIMITED"),
    ).toContain("temporarily rate limited");
    expect(pipelineStageLabel("seedance")).toBe("video generation");
    expect(pipelineStageLabel("omni")).toBe("video generation");
    expect(pipelineStageLabel("video_generation")).toBe("video generation");
    expect(pipelineStageLabel("assemble")).toBe("assemble");
    expect(merchantQaDetail("Audio: FAILED. Reason: silent. Stage: Seedance.")).toBe(
      "Audio: FAILED. Reason: silent. Stage: video generation.",
    );
  });

  it("composes a simple merchant instruction", () => {
    expect(composeInstructions({ text: "BM santai.", intent: "show", sellStyle: "soft" })).toContain(
      "demonstrating",
    );
    expect(
      composeInstructions({
        text: "BM santai.",
        tone: "warm",
        gender: "female",
        locale: "conversational_bm",
      }),
    ).toContain("Speaker style");
    expect(
      instructionText("BM santai.\nSpeaker style: Friendly, Female, Conversational BM."),
    ).toBe("BM santai.");
    expect(historyKind("draft")).toBe("Draft");
    expect(historyLabel({ status: "draft", merchant_instructions: "BM santai." })).toContain(
      "Draft",
    );
  });

  it("uses a scene clip when the assembled preview is not ready", () => {
    expect(
      libraryVideoSrc({
        scenes: [
          { order: 2, video_url: "/media/scene-2.mp4" },
          { order: 1, video_url: "/media/scene-1.mp4" },
        ],
      }),
    ).toBe("/media/scene-1.mp4");
    expect(libraryVideoSrc({ preview_url: "/media/preview.mp4", scenes: [{ video_url: "/media/scene-1.mp4" }] })).toBe(
      "/media/preview.mp4",
    );
    expect(libraryPosterSrc({ poster_url: "/media/ai/posters/open.jpg" })).toBe("/media/ai/posters/open.jpg");
    expect(libraryPosterSrc({})).toBe("");
  });

  it("keeps generated videos in the library and hides drafts", () => {
    expect(isLibraryVideo({ status: "ready_for_review" })).toBe(true);
    expect(isLibraryVideo({ status: "failed" })).toBe(true);
    expect(isLibraryVideo({ status: "draft" })).toBe(false);
    expect(isLibraryVideo({ status: "draft", preview_url: "/media/ai/previews/x.mp4" })).toBe(true);
    expect(isLibraryVideo({ status: "queued" })).toBe(true);
    expect(
      isLibraryVideo({ status: "assembling", preview_url: "/media/ai/previews/x.mp4" }),
    ).toBe(true);
    expect(isLibraryVideo({ status: "qa_running", preview_url: "/media/ai/previews/x.mp4" })).toBe(
      true,
    );
  });

  it("filters the video library by status, language, and product name", () => {
    expect(libraryStatusGroup("assembling")).toBe("in_progress");
    expect(libraryStatusGroup("ready_for_review")).toBe("ready");
    expect(libraryStatusGroup("failed")).toBe("failed");
    expect(libraryStatusGroup("exported")).toBe("approved");
    expect(
      matchesLibraryFilter(
        { status: "ready_for_review", product_name: "Vitamin C serum", language: "english" },
        { query: "serum", status: "ready", language: "english" },
      ),
    ).toBe(true);
    expect(
      matchesLibraryFilter(
        { status: "failed", product_name: "Vitamin C serum", language: "english" },
        { query: "serum", status: "ready", language: "" },
      ),
    ).toBe(false);
    expect(
      matchesLibraryFilter(
        { status: "approved", product_name: "Lip tint", language: "chinese" },
        { query: "", status: "all", language: "english" },
      ),
    ).toBe(false);
  });

  it("builds a download filename and paginates the library", () => {
    expect(libraryDownloadName({ id: 12, product_name: "Vitamin C / serum" })).toBe(
      "Vitamin-C-serum-12.mp4",
    );
    expect(libraryDownloadName({ id: 4, product_name: "  " })).toBe("video-4.mp4");
    expect(libraryPageCount(0)).toBe(1);
    expect(libraryPageCount(9, 8)).toBe(2);
    expect(libraryPageItems(["a", "b", "c", "d"], 2, 2)).toEqual(["c", "d"]);
    expect(libraryPageNumbers(1, 3)).toEqual([1, 2, 3]);
    expect(libraryPageNumbers(5, 12)).toEqual([1, "ellipsis", 4, 5, 6, "ellipsis", 12]);
  });

  it("summarizes QA without raw check names", () => {
    const summary = videoCheckSummary([
      { name: "price", status: "passed", detail: "ok" },
      { name: "claims", status: "warning", detail: "Review the claim" },
    ]);
    expect(summary.find((item) => item.label === "Price")?.status).toBe("passed");
    expect(summary.find((item) => item.label === "Claims")?.status).toBe("warning");
    expect(summary.every((item) => !/expired_offer|product_representation/.test(item.label))).toBe(
      true,
    );
  });

  it("never greens a visual check that did not run", () => {
    const layers = qaLayerSummary({
      product: {
        structural: { status: "passed", detail: "Each scene has a generated visual." },
        visual: { status: "not_checked", detail: "Visual comparison not available." },
      },
      presenter: {
        structural: { status: "not_checked", detail: "Not checked in the script." },
        visual: { status: "not_checked", detail: "Visual comparison not available." },
      },
    });
    expect(layers.find((item) => item.key === "product")?.kind).toBe("verified");
    expect(layers.find((item) => item.key === "product")?.mark).toBe("passed");
    expect(layers.find((item) => item.key === "product_visual")?.mark).toBe("not_checked");
    expect(layers.find((item) => item.key === "presenter")?.mark).toBe("not_checked");
    expect(visualQaRollup([]).mark).toBe("not_checked");
    expect(visualQaRollup([{ name: "product", status: "passed", detail: "ok" }]).mark).toBe(
      "not_checked",
    );
  });

  it("shows the incomplete QA case honestly and keeps approval blocked", () => {
    const checks = [
      {
        name: "product",
        status: "passed",
        detail: "Product information/claims match the product record.",
        source: "structural",
        verified: true,
      },
      {
        name: "presenter_consistency",
        status: "passed",
        detail: "Presenter lock is set.",
        source: "structural",
      },
      {
        name: "narration",
        status: "passed",
        detail: "Every scene has narration.",
        source: "structural",
      },
      {
        name: "ai_review",
        status: "warning",
        detail: "Automated language review was unavailable. Please review the copy manually or run AI Review again.",
        source: "provider",
        checked: false,
      },
      {
        name: "product_visual_consistency",
        status: "not_checked",
        detail: "Original product photos were not compared with the generated video.",
        source: "multimodal",
        checked: false,
        confidence: 0,
      },
    ];
    const cards = qaLayerSummary(undefined, checks);
    const visual = visualQaRollup(checks);
    expect(cards.find((item) => item.key === "product")?.mark).toBe("passed");
    expect(cards.find((item) => item.key === "product_visual")?.mark).toBe("not_checked");
    expect(cards.find((item) => item.key === "language")?.mark).toBe("warning");
    expect(visual.mark).toBe("not_checked");
    expect(visual.hasConfidence).toBe(false);
    expect(qaCardDetail(visual)).not.toMatch(/0% confidence/);
    expect(qaCardDetail(visual)).toMatch(/not compared|did not run/i);
    expect(qaStatusLabel("not_checked")).toBe("NOT CHECKED");
    expect(qaStatusLabel("skipped")).toBe("SKIPPED");
    expect(confidenceLabel(checks[3])).toBe("AI language review");
    expect(qaNeedsRerun(checks)).toBe(true);
    expect(qaIncomplete(checks)).toBe(true);
    expect(releaseBlockingIssues(checks, { hasPreview: true }).map((item) => item.name)).toContain(
      "product_visual_consistency",
    );
  });

  it("blocks silent audio even when an AAC-looking track could exist", () => {
    const blocked = releaseBlockingIssues([
      {
        name: "audio_silent",
        status: "failed",
        detail: "Audio: FAILED. Reason: Audio track is present but effectively silent. Stage: assembly.",
        source: "ffmpeg",
        severity: "high",
        reason: "Audio track is present but effectively silent",
        stage: "assembly",
      },
    ]);
    expect(blocked).toHaveLength(1);
    expect(blocked[0].name).toBe("audio_silent");
  });

  it("does not treat NOT CHECKED as a pass for release-blocking audio", () => {
    expect(
      releaseBlockingIssues([
        {
          name: "assembled_audio",
          status: "not_checked",
          detail: "Final assembled audio was not checked.",
        },
      ]),
    ).toHaveLength(1);
  });

  it("surfaces high-confidence visual issues for approval", () => {
    expect(
      seriousQaIssues([
        {
          name: "product_visual_consistency",
          status: "failed",
          detail: "Different product",
          source: "multimodal",
          confidence: 0.91,
          severity: "high",
        },
        {
          name: "product_visual_consistency",
          status: "warning",
          detail: "Maybe",
          source: "multimodal",
          confidence: 0.4,
          severity: "low",
        },
      ]),
    ).toHaveLength(1);
  });

  it("keeps 15-second scene counts and shows a provider failure", () => {
    expect(sceneCountForDuration(15)).toBe(3);
    expect(sceneCountForDuration(30)).toBe(5);
    expect(sceneCountForDuration(45)).toBe(6);
    expect(sceneCountForDuration(60)).toBe(6);
    const view = generationFailureView({
      order: 1,
      failure_code: "INVALID_DURATION",
      failure_message: "unsupported duration token=secret",
      provider: "omni",
      provider_request_id: "abc123",
    });
    expect(view.title).toBe("Scene 1 failed");
    expect(view.code).toBe("INVALID_DURATION");
    expect(view.requestId).toBe("abc123");
    expect(view.message).not.toContain("secret");
    expect(view.retryable).toBe(false);
    const rejected = generationFailureView({
      order: 2,
      failure_code: "INVALID_REQUEST",
      failure_message: "API key not valid. Please pass a valid API key.",
      provider: "omni",
      provider_request_id: "v1_interaction",
      pipeline_error: { status: 400, code: "INVALID_REQUEST", retryable: false, task_id: "v1_interaction" },
    });
    expect(rejected.summary).toBe(PROVIDER_STATUS_UNAVAILABLE);
    expect(rejected.summary).not.toMatch(/API key/i);
    expect(rejected.code).toBe("INVALID_REQUEST");
    expect(rejected.httpStatus).toBe(400);
    expect(rejected.requestId).toBe("v1_interaction");
    expect(rejected.message).toBe("API key not valid. Please pass a valid API key.");
    const staleQa = generationFailureView({ order: 2 });
    expect(staleQa.code).toBe("");
    expect(staleQa.provider).toBe("");
    expect(staleQa.category).toBe("qa");
    expect(staleQa.message).not.toMatch(/provider rejected/i);
    expect(rejected.retryable).toBe(false);
    expect(
      regenerationFailureNotice({
        errorMessage: "API key not valid. Please pass a valid API key.",
        scenes: [{ failure_code: "INVALID_REQUEST" }],
      }).summary,
    ).toBe(PROVIDER_STATUS_UNAVAILABLE);
    expect(
      productionPhase({
        status: "failed",
        error_message: "API key not valid. Please pass a valid API key.",
        scenes: [{ scene_status: "failed", failure_code: "INVALID_REQUEST", order: 1 }],
      }).mike,
    ).toBe(PROVIDER_STATUS_UNAVAILABLE);
    expect(sceneRetryBlocked([{ failure_code: "INVALID_REQUEST" }])).toBe(true);
    expect(sceneRetryBlocked([{ failure_code: "TIMEOUT", pipeline_error: { retryable: true } }])).toBe(false);
  });

  it("explains why bulk creation is disabled and enables a complete selection", () => {
    const blocked = bulkCreationState({
      styleSelected: false,
      productCount: 2,
      characterId: "12",
      characterName: "Mike Seah QA Presenter",
      characterHasVisual: false,
    });
    expect(blocked.enabled).toBe(false);
    expect(blocked.missing).toBe("Style Key required");
    const missingLook = bulkCreationState({
      styleSelected: true,
      productCount: 2,
      characterId: "12",
      characterName: "Mike Seah QA Presenter",
      characterHasVisual: false,
      characterBrandId: 1,
      productBrandIds: [1, 1],
      duration: 15,
    });
    expect(missingLook.enabled).toBe(false);
    expect(missingLook.missing).toContain("needs an approved Master Character Reference");
    const ready = bulkCreationState({
      styleSelected: true,
      productCount: 2,
      characterId: "12",
      characterName: "Mike Seah QA Presenter",
      characterHasVisual: true,
      characterBrandId: 1,
      productBrandIds: [1, 1],
      duration: 15,
      masterQaPassed: true,
    });
    expect(ready.enabled).toBe(true);
    expect(ready.missing).toBe("");
  });

  it("exposes review, approval, and failed project actions", () => {
    expect(projectPrimaryAction({ id: 8, status: "ready" }).label).toBe("Review Video");
    expect(projectPrimaryAction({ id: 8, status: "failed" }).label).toBe("View details");
    expect(projectPrimaryAction({ id: 8, status: "approved" }).label).toBe("View / Download");
    expect(identityPassed({ status: "passed", confidence: 0, comparison_performed: true, face_detected: true, required: true })).toBe(
      false,
    );
    expect(
      identityPassed({
        status: "passed",
        confidence: 0.9,
        comparison_performed: true,
        face_detected: true,
        required: true,
        threshold: 0.9,
      }),
    ).toBe(true);
    expect(narrationPassed({ required: true, status: "passed", speech_detected: false })).toBe(false);
    expect(narrationPassed({ required: true, status: "passed", speech_detected: true })).toBe(true);
    const gates = [
      {
        scene_key: "scene-1",
        identity: { required: true, status: "passed", confidence: 0.96, comparison_performed: true, face_detected: true, threshold: 0.9 },
        audio: { required: true, status: "passed", speech_detected: true },
      },
      {
        scene_key: "scene-3",
        identity: { required: true, status: "failed", confidence: 0.71, comparison_performed: true, face_detected: true, threshold: 0.9 },
        audio: { required: true, status: "passed", speech_detected: true },
      },
    ];
    expect(sceneGateFailures(gates).map((gate) => gate.scene_key)).toEqual(["scene-3"]);
    expect(approvalBlockSummary(gates)).toBe("Approval blocked. 1 scene QA check failed.");
    expect(
      projectCanApprove({
        status: "ready_for_review",
        qa_status: "passed",
        preview_url: "https://example.test/v.mp4",
        qa_results: { checks: [], scene_gates: gates },
      }),
    ).toBe(false);
    expect(projectCanApprove({ status: "ready", qa_status: "failed" })).toBe(false);
    expect(projectCanApprove({ status: "failed" })).toBe(false);
    expect(
      projectCanApprove({
        status: "ready",
        qa_status: "passed",
        preview_url: "https://example.test/v.mp4",
        qa_results: [],
      }),
    ).toBe(true);
  });
});

describe("api errors", () => {
  it("flattens field errors for the studio", () => {
    expect(flattenErrors({ product_id: ["Select a product."] })).toBe("Select a product.");
  });
});
