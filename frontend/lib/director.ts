import type { AmendmentRecommendation, CreativeConcept, Product, StudioScene, VideoProject } from "./api";
import { projectCanApprove } from "./studio";

export const OBJECTIVES = [
  { id: "buy", label: "Buy", hint: "Ask viewers to purchase." },
  { id: "enquire", label: "Enquire", hint: "Ask them to message or ask a question." },
  { id: "follow", label: "Follow", hint: "Grow your audience." },
  { id: "visit", label: "Visit", hint: "Invite them to a store or location." },
] as const;

export const MUST_REMAIN_OPTIONS = [
  { id: "product_appearance", label: "Product appearance" },
  { id: "logo", label: "Logo" },
  { id: "packaging", label: "Packaging" },
  { id: "presenter", label: "Presenter" },
  { id: "product_name", label: "Product name" },
  { id: "price", label: "Price" },
  { id: "brand_colors", label: "Brand colors" },
  { id: "other", label: "Other" },
] as const;

export const PLATFORM_OPTIONS = [
  { id: "", label: "Any platform" },
  { id: "tiktok", label: "TikTok" },
  { id: "instagram", label: "Instagram" },
  { id: "facebook", label: "Facebook" },
] as const;

export type CreativeBriefForm = {
  objective: string;
  customer: string;
  main_benefit: string;
  original_price: string;
  offer_price: string;
  offer_text: string;
  must_remain_exact: string[];
  must_not_show: string;
  platform: string;
  duration: number;
  legacy_instructions: string;
  location: string;
  presenter_ethnicity: string;
  presenter_ethnicity_custom: string;
  presenter_look: string;
};

export const emptyBrief = (duration = 45): CreativeBriefForm => ({
  objective: "",
  customer: "",
  main_benefit: "",
  original_price: "",
  offer_price: "",
  offer_text: "",
  must_remain_exact: ["product_appearance", "product_name", "price"],
  must_not_show: "",
  platform: "",
  duration,
  legacy_instructions: "",
  location: "",
  presenter_ethnicity: "",
  presenter_ethnicity_custom: "",
  presenter_look: "",
});

export function briefFromProject(project?: VideoProject | null, product?: Product | null): CreativeBriefForm {
  const brief = (project?.creative_brief || {}) as Record<string, unknown>;
  const snapshot = (project?.product_snapshot || {}) as Record<string, unknown>;
  const base = emptyBrief(project?.duration_seconds || 45);
  return {
    ...base,
    objective: String(brief.objective || ""),
    customer: String(brief.customer || brief.audience || ""),
    main_benefit: String(brief.main_benefit || brief.promise || ""),
    original_price: String(brief.original_price || snapshot.price || product?.price || ""),
    offer_price: String(brief.offer_price || ""),
    offer_text: String(brief.offer_text || brief.offer || snapshot.offer || product?.offer || ""),
    must_remain_exact: Array.isArray(brief.must_remain_exact)
      ? (brief.must_remain_exact as string[])
      : base.must_remain_exact,
    must_not_show: String(brief.must_not_show || ""),
    platform: String(brief.platform || ""),
    duration: Number(brief.duration || project?.duration_seconds || 45),
    legacy_instructions: String(brief.legacy_instructions || ""),
    location: String(brief.location || ""),
    presenter_ethnicity: String(
      (brief.presenter as { ethnicity_key?: string; ethnicity?: string } | undefined)?.ethnicity_key ||
        (brief.presenter as { ethnicity?: string } | undefined)?.ethnicity ||
        "",
    ),
    presenter_ethnicity_custom: String(
      (brief.presenter as { ethnicity_custom?: string } | undefined)?.ethnicity_custom || "",
    ),
    presenter_look: String((brief.presenter as { look?: string } | undefined)?.look || ""),
  };
}

export function briefIsReady(brief: CreativeBriefForm): boolean {
  return Boolean(brief.objective && brief.customer.trim() && brief.main_benefit.trim());
}

export type ConceptCreateCheck = {
  id: string;
  label: string;
  ready: boolean;
  hint: string;
};

export function conceptCreateChecks(input: {
  hasProduct: boolean;
  objective: string;
  customer: string;
  mainBenefit: string;
  generateCharacter: boolean;
  hasCharacter: boolean;
  characterReady: boolean;
}): ConceptCreateCheck[] {
  const characterOk = input.generateCharacter || input.characterReady;
  let characterHint = "Select a character from the list, or check Generate character.";
  if (input.hasCharacter && !input.characterReady && !input.generateCharacter) {
    characterHint =
      "This character needs an approved master photo. Open Characters to approve it, or check Generate character.";
  }
  return [
    { id: "product", label: "Product", ready: input.hasProduct, hint: "Select a product." },
    {
      id: "objective",
      label: "Viewer action",
      ready: Boolean(input.objective),
      hint: "Pick what you want viewers to do (buy, enquire, follow, or visit).",
    },
    {
      id: "customer",
      label: "Customer",
      ready: Boolean(input.customer.trim()),
      hint: "Say who the customer is.",
    },
    {
      id: "benefit",
      label: "Main benefit",
      ready: Boolean(input.mainBenefit.trim()),
      hint: "Say the main product benefit.",
    },
    { id: "character", label: "Character", ready: characterOk, hint: characterHint },
  ];
}

export function presenterPayload(brief: CreativeBriefForm, gender = "") {
  const custom = brief.presenter_ethnicity_custom.trim();
  const ethnicity =
    brief.presenter_ethnicity === "custom" ? custom : brief.presenter_ethnicity;
  return {
    ethnicity,
    ethnicity_key: brief.presenter_ethnicity,
    ethnicity_custom: custom,
    ethnicity_label: brief.presenter_ethnicity === "custom" ? custom : "",
    look: brief.presenter_look.trim(),
    gender,
  };
}

export function formatClock(seconds?: number): string {
  const value = Math.max(0, Math.round(Number(seconds || 0)));
  const mins = Math.floor(value / 60);
  const secs = value % 60;
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

export function sceneLabel(status?: string): string {
  const labels: Record<string, string> = {
    draft: "Draft",
    ready: "Ready",
    generating: "Generating",
    generated: "Generated",
    qa_warning: "QA warning",
    qa_failed: "QA failed",
    approved: "Approved",
    regenerating: "Regenerating",
    failed: "Failed",
  };
  return labels[status || ""] || status || "Draft";
}

export function sceneStatusIcon(status?: string): string {
  if (status === "approved" || status === "generated") return "✓";
  if (status === "generating" || status === "regenerating") return "⏳";
  if (status === "failed" || status === "qa_failed") return "!";
  if (status === "qa_warning") return "⚠";
  return "○";
}

export function conceptsFrom(project?: VideoProject | null): CreativeConcept[] {
  return (project?.creative_directions || []).filter((item) => item && item.title);
}

export function amendmentsFrom(project?: VideoProject | null): AmendmentRecommendation[] {
  return project?.amendment_recommendations || [];
}

export function directorResumeStep(project?: VideoProject | null): "compose" | "concepts" | "storyboard" | null {
  if (!project || project.status !== "draft") return null;
  if (project.scenes?.length && project.selected_concept_id) return "storyboard";
  if (conceptsFrom(project).length) return "concepts";
  return "compose";
}

export function canVisitStudioStep(step: string, project?: VideoProject | null): boolean {
  const concepts = conceptsFrom(project);
  const scenes = project?.scenes || [];
  const hasPreview = Boolean(project?.preview_url || project?.final_url || project?.export_url);
  const status = project?.status || "";
  if (step === "compose") return true;
  if (step === "concepts") return concepts.length > 0;
  if (step === "storyboard") return Boolean(project?.selected_concept_id) || scenes.length > 0;
  if (step === "generate") {
    return (
      scenes.length > 0 ||
      ["failed", "queued", "analyzing", "generating", "generating_video", "correcting"].includes(status)
    );
  }
  if (step === "review") {
    return hasPreview || status === "ready" || status === "ready_for_review";
  }
  if (step === "approve") {
    return projectCanApprove(project || { status });
  }
  return false;
}

export function sceneVoice(scene: StudioScene): string {
  return scene.voice_over || scene.narration || "";
}

export function sceneCaption(scene: StudioScene): string {
  return scene.on_screen_caption || scene.caption || "";
}

export function sceneShot(scene: StudioScene): string {
  return scene.shot_description || scene.visual || "";
}
