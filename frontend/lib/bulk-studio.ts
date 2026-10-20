import type { BulkGeneration, BulkGenerationItem, BulkStudioMode, BulkVariation } from "./api";

export const BULK_STUDIO_STEPS = [
  { id: "mode", label: "Mode" },
  { id: "configure", label: "Configure" },
  { id: "plan", label: "Plan" },
  { id: "generate", label: "Generate" },
] as const;

export type BulkStudioStepId = (typeof BULK_STUDIO_STEPS)[number]["id"];

export const BULK_MODES: Array<{
  id: BulkStudioMode;
  label: string;
  title: string;
  description: string;
  example: string;
}> = [
  {
    id: "character",
    label: "Character",
    title: "Generate videos for a character",
    description: "Keep the same character identity while generating multiple different video concepts, stories, locations, actions, or hooks.",
    example: "Character: Sarah · Videos: 10",
  },
  {
    id: "product",
    label: "Product",
    title: "Generate videos for a product",
    description: "Keep the same product while generating multiple marketing videos around it.",
    example: "Product: Product A · Videos: 10",
  },
  {
    id: "existing_video",
    label: "Existing Video",
    title: "Make copies of this video flow",
    description: "Reuse the exact story, scenes, timing, dialogue, and CTA from a Studio video. Choose only what should change.",
    example: "Video A · 10 same-flow copies",
  },
  {
    id: "reference_location",
    label: "Reference → Locations",
    title: "Reuse story, change location",
    description: "Analyze one reference video, then keep the story and character while changing locations.",
    example: "Same story · 10 locations",
  },
  {
    id: "reference_character",
    label: "Reference → Characters",
    title: "Reuse story, change character",
    description: "Analyze one reference video, then keep the story and location while changing characters.",
    example: "Same story · 10 characters",
  },
];

export const BULK_LOCK_LABELS: Record<string, string> = {
  character: "Character identity",
  product: "Product identity",
  product_appearance: "Product appearance",
  brand: "Brand",
  voice: "Voice / language",
  price: "Price",
  cta: "CTA",
  offer: "Offer",
  story: "Story",
  scenes: "Scene structure",
  script: "Script",
  dialogue: "Dialogue",
  timing: "Timing",
  camera: "Camera intent",
  location: "Location",
  duration: "Duration",
};

export const BULK_VARIABLE_LABELS: Record<string, string> = {
  story: "Story",
  location: "Location",
  action: "Action",
  camera: "Camera",
  hook: "Hook",
  environment: "Environment",
  character: "Character",
};

export const BULK_COUNT_MIN = 1;
export const BULK_COUNT_MAX = 10;

export const REFERENCE_VIDEO_TYPES = ["video/mp4", "video/quicktime", "video/webm", "video/x-m4v"];
export const REFERENCE_VIDEO_ACCEPT = "video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.m4v";

export function isReferenceMode(mode?: BulkStudioMode | "") {
  return mode === "reference_location" || mode === "reference_character";
}

export function isSameFlowMode(mode?: BulkStudioMode | "") {
  return mode === "existing_video";
}

export function configureFields(mode: BulkStudioMode) {
  return {
    needsCharacter: mode === "character",
    needsCharacters: mode === "reference_character",
    needsReference: isReferenceMode(mode),
    needsSourceVideo: isSameFlowMode(mode),
    productRequired: true,
    countEditable: mode !== "reference_character",
  };
}

export function bulkStepForStatus(status?: string): BulkStudioStepId {
  if (!status || status === "draft" || status === "analyzing") return "configure";
  if (status === "plan_ready") return "plan";
  return "generate";
}

export function canGeneratePlan(input: {
  mode: BulkStudioMode | "";
  productId?: number | "";
  characterId?: number | "";
  characterIds?: number[];
  hasReference?: boolean;
  analyzed?: boolean;
}) {
  if (!input.mode || !input.productId) return false;
  if (input.mode === "character" && !input.characterId) return false;
  if (input.mode === "reference_character" && !(input.characterIds || []).length) return false;
  if (isReferenceMode(input.mode) && !input.hasReference) return false;
  if (isSameFlowMode(input.mode) && !input.hasReference) return false;
  return true;
}

export function planRows(batch?: BulkGeneration | null): BulkVariation[] {
  if (batch?.generation_plan?.length) return batch.generation_plan;
  return (batch?.items || []).map((item) => ({
    sequence: item.sequence,
    title: item.title,
    ...item.variation_config,
  }));
}

export function itemStatusLabel(item: BulkGenerationItem) {
  if (item.status === "failed") return item.error_message || "Failed";
  if (item.status === "generating" || item.status === "queued") {
    const metrics = item.video_project?.generation_metrics;
    const rows = metrics?.scenes || [];
    const total = metrics?.scene_count || 0;
    const done = rows.filter((scene) => scene.status === "completed").length;
    const retrying = rows.filter((scene) => scene.status === "retrying").length;
    const stage = item.video_project?.stage_label || (item.status === "queued" ? "Queued" : "Generating");
    if (total) {
      const retry = retrying ? ` · retrying ${retrying}` : "";
      return `${stage} · ${done} / ${total} scenes${retry}`;
    }
    return stage;
  }
  if (item.status === "completed") return "Ready for review";
  if (item.status === "cancelled") return "Cancelled";
  return "Planned";
}

export function bulkProgress(batch?: BulkGeneration | null) {
  const items = batch?.items || [];
  const total = items.length || batch?.requested_count || 0;
  const completed = items.filter((item) => item.status === "completed").length;
  const failed = items.filter((item) => item.status === "failed").length;
  const generating = items.filter((item) => item.status === "generating" || item.status === "queued").length;
  const percent = total ? Math.round((completed / total) * 100) : 0;
  return { total, completed, failed, generating, percent };
}

export function isBulkBusy(status?: string) {
  return status === "queued" || status === "generating" || status === "analyzing";
}

export function reviewHref(projectId?: number | null) {
  if (!projectId) return "";
  return `/brand/studio?project=${projectId}&step=review`;
}

export function canUseLibraryVideoForBulk(item?: { preview_url?: string; final_url?: string; export_url?: string } | null) {
  return Boolean(item && (item.export_url || item.final_url || item.preview_url));
}

export function bulkFromLibraryHref(item?: { id?: number } | null) {
  if (!item?.id) return "";
  return `/brand/studio/bulk?source=${item.id}`;
}

export function parseBulkCount(value: string | number, fallback = 10) {
  const parsed = typeof value === "number" ? value : Number.parseInt(String(value).trim(), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(BULK_COUNT_MAX, Math.max(BULK_COUNT_MIN, parsed));
}

export function acceptedReferenceVideo(file?: File | null) {
  if (!file) return false;
  const name = file.name.toLowerCase();
  return file.type.startsWith("video/") || [".mp4", ".mov", ".webm", ".m4v"].some((ext) => name.endsWith(ext));
}
