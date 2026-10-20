export const STUDIO_STEPS = [
  { id: "compose", label: "Brief" },
  { id: "concepts", label: "Concepts" },
  { id: "storyboard", label: "Storyboard" },
  { id: "generate", label: "Generate" },
  { id: "review", label: "Review" },
  { id: "approve", label: "Approve" },
] as const;

export type StudioStepId = (typeof STUDIO_STEPS)[number]["id"];

export const LANGUAGE_OPTIONS = [
  {
    id: "conversational_bm",
    label: "Conversational BM",
    hint: "Natural Bahasa Malaysia, as if speaking to a friend.",
    ready: true,
  },
  {
    id: "formal_bm",
    label: "Formal BM",
    hint: "Polite Bahasa Malaysia for a trusted brand.",
    ready: true,
  },
  {
    id: "bm_english",
    label: "BM + English",
    hint: "The mix Malaysian shoppers already use.",
    ready: true,
  },
  {
    id: "english",
    label: "English",
    hint: "Clear spoken English.",
    ready: true,
  },
  {
    id: "chinese",
    label: "Chinese (Mandarin)",
    hint: "Spoken Standard Mandarin. Not Cantonese or Hokkien.",
    ready: true,
  },
  {
    id: "cantonese",
    label: "Cantonese (粵語)",
    hint: "Spoken Cantonese. Not Mandarin.",
    ready: true,
  },
  {
    id: "hokkien",
    label: "Hokkien (福建話)",
    hint: "Spoken Hokkien. Not Mandarin or Cantonese.",
    ready: true,
  },
  {
    id: "mandarin_my",
    label: "Malaysian Mandarin",
    hint: "Prepared for Malaysian Mandarin narration.",
    ready: true,
  },
  {
    id: "tamil_my",
    label: "Malaysian Tamil",
    hint: "Prepared for Malaysian Tamil narration.",
    ready: true,
  },
] as const;

export const PRESENTER_ETHNICITY_OPTIONS = [
  { id: "", label: "Any / let AI choose" },
  { id: "european", label: "European" },
  { id: "chinese", label: "Chinese" },
  { id: "malaysian_chinese", label: "Malaysian Chinese" },
  { id: "malay", label: "Malay" },
  { id: "indian", label: "Indian" },
  { id: "african", label: "African" },
  { id: "middle_eastern", label: "Middle Eastern" },
  { id: "japanese", label: "Japanese" },
  { id: "korean", label: "Korean" },
  { id: "southeast_asian", label: "Southeast Asian" },
  { id: "latino", label: "Latino / Hispanic" },
  { id: "mixed", label: "Mixed heritage" },
  { id: "custom", label: "Custom — describe below" },
] as const;

export const PRESENTER_PHOTO_ANGLES = [
  { id: "front", label: "Front" },
  { id: "left", label: "Left" },
  { id: "right", label: "Right" },
  { id: "up", label: "Looking up" },
  { id: "down", label: "Looking down" },
] as const;

export const STYLE_OPTIONS = [
  { id: "warm", label: "Friendly", hint: "Warm and close." },
  { id: "calm", label: "Casual", hint: "Relaxed and natural." },
  { id: "bold", label: "Energetic", hint: "Punchy and confident." },
  { id: "luxury", label: "Premium", hint: "Refined and polished." },
] as const;

export const GENDER_OPTIONS = [
  { id: "female", label: "Female" },
  { id: "male", label: "Male" },
  { id: "neutral", label: "Neutral" },
] as const;

export const SELL_STYLE_OPTIONS = [
  { id: "soft", label: "Soft sell", hint: "Gentle and helpful." },
  { id: "balanced", label: "Balanced", hint: "Clear benefit, then the offer." },
  { id: "strong", label: "Strong offer", hint: "Lead with the promo." },
] as const;

export const CONTENT_INTENTS = [
  {
    id: "show",
    label: "Show the product",
    hint: "See how it looks and works.",
    instruction: "Focus on demonstrating how the product works.",
  },
  {
    id: "question",
    label: "Answer a customer question",
    hint: "Clear up a common worry.",
    instruction: "Answer a common customer question using only approved facts.",
  },
  {
    id: "offer",
    label: "Promote today's offer",
    hint: "Share the current promo.",
    instruction: "Explain the verified offer. Do not invent a discount.",
  },
] as const;

export const DURATION_OPTIONS = [15, 30, 45, 60] as const;

export const STUDIO_BULK_MAX = 10;

export const BULK_GENDER_MODES = [
  { id: "female", label: "All female" },
  { id: "male", label: "All male" },
  { id: "mix", label: "Mix" },
] as const;

export type BulkGenderMode = (typeof BULK_GENDER_MODES)[number]["id"];
export type BulkDurationMode = "fixed" | "mix";

export type StudioBulkJobInput = {
  conceptIds: string[];
  characterIds?: Array<string | number>;
  generateCharacter?: boolean;
  genderMode?: BulkGenderMode | string;
  durationMode?: BulkDurationMode | string;
  durationSeconds?: number;
  count?: number | null;
};

export type StudioBulkJob = {
  concept_id: string;
  character_id: number | null;
  generate_character: boolean;
  gender: string;
  duration: number;
  index: number;
};

export function studioBulkCharacterSlots(
  characterIds?: Array<string | number>,
  generateCharacter = false,
): Array<{ character_id: number | null; generate_character: boolean }> {
  const seen = new Set<number>();
  const slots: Array<{ character_id: number | null; generate_character: boolean }> = [];
  for (const raw of characterIds || []) {
    const value = Number(raw);
    if (!Number.isFinite(value) || value <= 0 || seen.has(value)) continue;
    seen.add(value);
    slots.push({ character_id: value, generate_character: false });
  }
  if (generateCharacter) slots.push({ character_id: null, generate_character: true });
  return slots;
}

export function expandStudioBulkJobs(input: StudioBulkJobInput): {
  jobs: StudioBulkJob[];
  combinationCount: number;
  error: string;
} {
  const conceptIds = Array.from(new Set((input.conceptIds || []).map((item) => String(item || "").trim()).filter(Boolean)));
  const slots = studioBulkCharacterSlots(input.characterIds, Boolean(input.generateCharacter));
  if (!conceptIds.length) {
    return { jobs: [], combinationCount: 0, error: "Select at least one concept." };
  }
  if (!slots.length) {
    return { jobs: [], combinationCount: 0, error: "Select a character or check Generate character." };
  }
  const combos = conceptIds.flatMap((concept_id) => slots.map((slot) => ({ concept_id, ...slot })));
  const requestedRaw = input.count == null || input.count === ("" as never) ? combos.length : Number(input.count);
  if (!Number.isFinite(requestedRaw) || requestedRaw < 1) {
    return { jobs: [], combinationCount: combos.length, error: "Generate at least one video." };
  }
  const requested = Math.max(requestedRaw, conceptIds.length);
  if (requested > STUDIO_BULK_MAX) {
    return {
      jobs: [],
      combinationCount: combos.length,
      error: `Create up to ${STUDIO_BULK_MAX} videos at a time.`,
    };
  }
  const mixDuration = String(input.durationMode || "fixed").toLowerCase() === "mix";
  const duration = mixDuration ? 0 : Number(input.durationSeconds || 45);
  if (!mixDuration && !(DURATION_OPTIONS as readonly number[]).includes(duration as (typeof DURATION_OPTIONS)[number])) {
    return { jobs: [], combinationCount: combos.length, error: "Choose 15, 30, 45, 60 seconds, or Mix." };
  }
  const genderRaw = String(input.genderMode || "female").toLowerCase();
  const gender = genderRaw === "male" || genderRaw === "all_male" ? "male" : genderRaw === "mix" || genderRaw === "mixed" ? "mix" : "female";
  const genders = gender === "mix" ? ["female", "male"] : [gender];
  const durations = mixDuration ? [...DURATION_OPTIONS] : [duration];
  const sequence =
    requested >= combos.length
      ? Array.from({ length: requested }, (_, index) => combos[index % combos.length])
      : (() => {
          const picked: typeof combos = [];
          const seen = new Set<string>();
          for (const combo of combos) {
            if (seen.has(combo.concept_id)) continue;
            picked.push(combo);
            seen.add(combo.concept_id);
            if (picked.length >= requested) return picked;
          }
          return picked;
        })();
  const jobs = sequence.map((combo, index) => ({
    concept_id: combo.concept_id,
    character_id: combo.character_id,
    generate_character: combo.generate_character,
    gender: genders[index % genders.length],
    duration: durations[index % durations.length],
    index,
  }));
  return { jobs, combinationCount: combos.length, error: "" };
}

export const SCENE_COUNTS: Record<(typeof DURATION_OPTIONS)[number], number> = {
  15: 3,
  30: 5,
  45: 6,
  60: 6,
};

export function sceneCountForDuration(duration: number): number {
  if (duration in SCENE_COUNTS) return SCENE_COUNTS[duration as keyof typeof SCENE_COUNTS];
  return 0;
}

const NON_RETRYABLE_CODES = new Set([
  "INVALID_REQUEST",
  "INVALID_DURATION",
  "INVALID_MEDIA",
  "MISSING_CONFIGURATION",
  "UNSUPPORTED_FORMAT",
  "AUTHENTICATION",
  "INVALID_PROMPT",
  "QUOTA",
]);

export function sanitizeProviderMessage(message: string): string {
  return String(message || "")
    .replace(/AIza[0-9A-Za-z_-]{8,}/g, "[redacted]")
    .replace(/sk-[A-Za-z0-9]{8,}/g, "[redacted]")
    .replace(/Bearer\s+\S+/gi, "Bearer [redacted]")
    .replace(/(api[_-]?key|access[_-]?token|token|secret|password)\s*[:=]\s*\S+/gi, "$1=[redacted]")
    .trim();
}

export type GenerationFailureView = {
  title: string;
  provider: string;
  message: string;
  summary: string;
  code: string;
  httpStatus: number;
  requestId: string;
  category: string;
  retryable: boolean;
};

export function generationFailureView(scene: {
  order?: number;
  error?: string;
  failure_code?: string;
  failure_message?: string;
  provider?: string;
  provider_request_id?: string;
  pipeline_error?: {
    detail?: string;
    code?: string;
    provider?: string;
    task_id?: string;
    status?: number;
    error_type?: string;
    retryable?: boolean;
  };
}): GenerationFailureView {
  const pipe = scene.pipeline_error || {};
  const code = String(scene.failure_code || pipe.code || "").toUpperCase();
  const rawMessage = scene.failure_message || scene.error || pipe.detail || "";
  const providerFailure = Boolean(code || rawMessage || scene.provider || pipe.provider);
  const message = sanitizeProviderMessage(
    rawMessage || (providerFailure ? "The video provider rejected this scene." : "This scene needs another look before it can be approved."),
  );
  const category = String(pipe.error_type || (providerFailure ? categoryForCode(code, message) : "qa"));
  const retryable =
    pipe.retryable === true ? !NON_RETRYABLE_CODES.has(code) : pipe.retryable === false ? false : !NON_RETRYABLE_CODES.has(code);
  const notice = regenerationFailureNotice({ scenes: [scene] });
  return {
    title: `Scene ${scene.order || 1} failed`,
    provider: scene.provider || pipe.provider || (providerFailure ? "Omni" : ""),
    message,
    summary: notice.summary,
    code: code || (providerFailure ? "PROVIDER_REJECTION" : ""),
    httpStatus: Number(pipe.status || 0),
    requestId: scene.provider_request_id || pipe.task_id || "",
    category,
    retryable: Boolean(code) ? retryable : true,
  };
}

function categoryForCode(code: string, message: string): string {
  if (code === "INVALID_REQUEST") return "invalid_request";
  if (code === "AUTHENTICATION") return "authentication";
  if (code === "QUOTA") return "quota";
  if (code === "INVALID_DURATION") return "configuration";
  if (code === "INVALID_MEDIA") return "invalid_media";
  if (code === "INVALID_PROMPT") return "invalid_prompt";
  if (code === "TIMEOUT") return "timeout";
  if (code === "PROVIDER_UNAVAILABLE") return "provider_unavailable";
  if (/timeout/i.test(message)) return "timeout";
  if (/quota|credit/i.test(message)) return "quota";
  if (/duration/i.test(message)) return "configuration";
  return "provider_rejection";
}

export function sceneRetryBlocked(scenes: { failure_code?: string; pipeline_error?: { retryable?: boolean; code?: string } }[]): boolean {
  return scenes.some((scene) => {
    const code = String(scene.failure_code || scene.pipeline_error?.code || "").toUpperCase();
    if (!code) return false;
    if (NON_RETRYABLE_CODES.has(code)) return true;
    return scene.pipeline_error?.retryable === false;
  });
}

export type BulkRequirement = {
  id: string;
  label: string;
  ok: boolean;
};

export function bulkCreationState(input: {
  pending?: boolean;
  styleSelected: boolean;
  productCount: number;
  characterId?: string;
  characterName?: string;
  characterHasVisual?: boolean;
  characterBrandId?: number | null;
  productBrandIds?: number[];
  duration?: number | null;
  voiceReady?: boolean;
  masterQaPassed?: boolean;
}): { enabled: boolean; requirements: BulkRequirement[]; missing: string } {
  const brands = input.productBrandIds || [];
  const sameBrand = brands.length === 0 || brands.every((id) => id === brands[0]);
  const characterOk = !input.characterId || Boolean(input.characterHasVisual);
  const characterBrandOk =
    !input.characterId ||
    brands.length === 0 ||
    brands.every((id) => input.characterBrandId == null || id === input.characterBrandId);
  const durationOk = !input.duration || (DURATION_OPTIONS as readonly number[]).includes(input.duration);
  const masterOk = input.masterQaPassed !== false;
  const requirements: BulkRequirement[] = [
    { id: "master_qa", label: "Master video passed QA", ok: masterOk },
    { id: "style", label: "Style Key selected", ok: input.styleSelected },
    {
      id: "products",
      label: input.productCount ? `${input.productCount} product${input.productCount === 1 ? "" : "s"} selected` : "At least 1 product selected",
      ok: input.productCount > 0,
    },
    {
      id: "character",
      label: input.characterId ? "Character selected" : "Character optional",
      ok: true,
    },
    { id: "duration", label: "Valid duration", ok: durationOk },
    { id: "voice", label: "Valid voice configuration", ok: input.voiceReady !== false },
    { id: "visual", label: input.characterName ? `${input.characterName} has a usable look` : "Character look", ok: characterOk },
    { id: "brand", label: "Character matches the product brand", ok: sameBrand && characterBrandOk },
  ];
  const blocking = requirements.filter((item) => !item.ok && item.id !== "character");
  const missing = !masterOk
    ? "Master video must pass QA before bulk generation"
    : !input.styleSelected
    ? "Style Key required"
    : input.productCount < 1
      ? "Select a product"
      : !durationOk
        ? "Select a duration"
        : input.voiceReady === false
          ? "Voice configuration is incomplete"
          : !characterOk
            ? `${input.characterName || "This character"} needs an approved Master Character Reference.`
            : !sameBrand || !characterBrandOk
              ? "Choose products from the character's brand."
              : "";
  return {
    enabled: !input.pending && blocking.length === 0,
    requirements,
    missing,
  };
}

export function projectPrimaryAction(item: {
  id: number;
  status: string;
  selected_concept_id?: string;
  scenes?: { id?: number }[];
  qa_status?: string;
  preview_url?: string;
  final_url?: string;
  export_url?: string;
}): { label: string; href: string } {
  const id = item.id;
  if (item.status === "failed") {
    return { label: "View details", href: `/brand/studio?project=${id}&step=generate` };
  }
  if (ACTIVE_STATUSES.has(item.status)) {
    return { label: "View Generation", href: `/brand/studio?project=${id}&step=generate` };
  }
  if (item.status === "ready" || item.status === "ready_for_review") {
    return { label: "Review Video", href: `/brand/studio?project=${id}&step=review` };
  }
  if (item.status === "approved" || item.status === "exported") {
    return { label: "View / Download", href: `/brand/videos?id=${id}` };
  }
  if (item.scenes?.length && item.selected_concept_id) {
    return { label: "Continue", href: `/brand/studio?project=${id}&step=storyboard` };
  }
  return { label: "Continue", href: `/brand/studio?project=${id}&step=compose` };
}

export const IDENTITY_PASS_THRESHOLD = 0.9;

export type SceneIdentityView = {
  status?: string;
  required?: boolean;
  confidence?: number | null;
  threshold?: number;
  comparison_performed?: boolean;
  face_detected?: boolean;
  reason?: string;
  reference_url?: string;
  generated_face_url?: string;
  character_name?: string;
};

export type SceneAudioView = {
  status?: string;
  required?: boolean;
  has_audio_stream?: boolean;
  speech_detected?: boolean;
  duration_seconds?: number | null;
  reason?: string;
};

export type SceneGateView = {
  scene_key: string;
  order?: number;
  label?: string;
  identity?: SceneIdentityView;
  audio?: SceneAudioView;
};

export function identityPassed(identity: SceneIdentityView | undefined): boolean {
  if (!identity || identity.required === false) return true;
  if (identity.comparison_performed !== true) return false;
  if (identity.face_detected !== true) return false;
  if (identity.status !== "passed") return false;
  if (typeof identity.confidence !== "number" || Number.isNaN(identity.confidence)) return false;
  const threshold =
    typeof identity.threshold === "number" && !Number.isNaN(identity.threshold)
      ? identity.threshold
      : IDENTITY_PASS_THRESHOLD;
  return identity.confidence >= threshold;
}

export function narrationPassed(audio: SceneAudioView | undefined): boolean {
  if (!audio || audio.required === false) return true;
  return audio.status === "passed" && audio.speech_detected === true;
}

export function sceneGateFailures(gates: SceneGateView[] | undefined): SceneGateView[] {
  return (gates || []).filter((gate) => {
    const identityRequired = gate.identity?.required !== false && gate.identity;
    const audioRequired = gate.audio?.required === true;
    if (!identityRequired && !audioRequired) return false;
    if (identityRequired && !identityPassed(gate.identity)) return true;
    if (audioRequired && !narrationPassed(gate.audio)) return true;
    return false;
  });
}

export function approvalBlockSummary(gates: SceneGateView[] | undefined): string {
  const failed = sceneGateFailures(gates);
  if (!failed.length) return "";
  const count = failed.length;
  return `Approval blocked. ${count} scene QA check${count === 1 ? "" : "s"} failed.`;
}

export function identityScoreLabel(identity: SceneIdentityView | undefined): string {
  if (typeof identity?.confidence !== "number" || Number.isNaN(identity.confidence)) return "";
  return `${Math.round(identity.confidence * 100)}%`;
}

export function projectCanApprove(item: {
  status: string;
  qa_status?: string;
  preview_url?: string;
  final_url?: string;
  export_url?: string;
  qa_results?: { checks?: QaCheck[]; scene_gates?: SceneGateView[] } | QaCheck[];
}): boolean {
  if (item.status === "approved" || item.status === "exported") return true;
  if (item.status !== "ready" && item.status !== "ready_for_review") return false;
  if (item.qa_status !== "passed") return false;
  const checks = Array.isArray(item.qa_results) ? item.qa_results : item.qa_results?.checks;
  const gates = Array.isArray(item.qa_results) ? undefined : item.qa_results?.scene_gates;
  if (sceneGateFailures(gates).length) return false;
  const hasPreview = Boolean(item.preview_url || item.final_url || item.export_url);
  return releaseBlockingIssues(checks, { hasPreview }).length === 0;
}

export const ACTIVE_STATUSES = new Set([
  "queued",
  "analyzing",
  "brief_ready",
  "script_ready",
  "planning",
  "generating",
  "generating_assets",
  "generating_video",
  "generating_voice",
  "processing",
  "assembling",
  "qa",
  "qa_running",
  "correcting",
]);

export const PROGRESS_STEPS = [
  {
    id: "understand",
    label: "Understanding your product",
    statuses: ["queued", "analyzing"],
  },
  {
    id: "script",
    label: "Creating the script",
    statuses: ["brief_ready", "script_ready"],
  },
  {
    id: "shots",
    label: "Planning the shots",
    statuses: ["planning"],
  },
  {
    id: "video",
    label: "Creating video",
    statuses: ["generating", "generating_assets", "generating_video"],
  },
  {
    id: "voice",
    label: "Joining scenes",
    statuses: ["generating_voice", "processing", "assembling"],
  },
  {
    id: "check",
    label: "Checking the video",
    statuses: ["qa", "qa_running", "correcting"],
  },
] as const;

export function stepIndex(id: StudioStepId): number {
  return STUDIO_STEPS.findIndex((step) => step.id === id);
}

export function nextStep(id: StudioStepId): StudioStepId {
  const index = stepIndex(id);
  return STUDIO_STEPS[Math.min(index + 1, STUDIO_STEPS.length - 1)].id;
}

export function previousStep(id: StudioStepId): StudioStepId {
  const index = stepIndex(id);
  return STUDIO_STEPS[Math.max(index - 1, 0)].id;
}

export function reviewStepForStatus(status: string): StudioStepId {
  if (ACTIVE_STATUSES.has(status)) return "generate";
  if (status === "failed") return "generate";
  if (status === "exported" || status === "approved") return "approve";
  if (status === "ready" || status === "ready_for_review") return "review";
  if (status === "draft") return "compose";
  return "generate";
}

export function progressStepIndex(status: string): number {
  const index = PROGRESS_STEPS.findIndex((step) =>
    (step.statuses as readonly string[]).includes(status),
  );
  if (index >= 0) return index;
  if (ACTIVE_STATUSES.has(status)) return 0;
  return PROGRESS_STEPS.length;
}

export type ProductionPhaseKey =
  | "ready"
  | "preparing_story"
  | "generating_scenes"
  | "generating_video"
  | "running_checks"
  | "ready_for_review"
  | "changes_requested"
  | "approved"
  | "exporting"
  | "failed";

export type ProductionPhase = {
  key: ProductionPhaseKey;
  label: string;
  sara: string;
  mike: string;
};

type PhaseSource = {
  character_name?: string;
  voice_summary?: string;
  status?: string;
  stage_label?: string;
  error_message?: string;
  error_type?: string;
  preview_url?: string;
  final_url?: string;
  export_url?: string;
  scenes?: {
    scene_status?: string;
    title?: string;
    order?: number;
    failure_code?: string;
    failure_message?: string;
    provider?: string;
    provider_request_id?: string;
    pipeline_error?: FailureScene["pipeline_error"];
  }[];
  selected_concept_id?: string;
  creative_directions?: { title?: string }[];
  qa_results?: { checks?: QaCheck[] };
};

export function productionPhase(project?: PhaseSource | null): ProductionPhase {
  const phase = productionPhaseBody(project);
  const name = (project?.character_name || "").trim();
  if (!name) return phase;
  const voice = (project?.voice_summary || "").trim();
  return {
    ...phase,
    sara: `${phase.sara} ${name} is selected as the primary character. Visual identity stays consistent across scenes.`,
    mike: voice
      ? `${phase.mike} Character locked. Voice preference: ${voice}. Spoken audio is generated with the video.`
      : `${phase.mike} Character locked.`,
  };
}

function productionPhaseBody(project?: PhaseSource | null): ProductionPhase {
  const status = project?.status || "";
  const stage = (project?.stage_label || "").trim();
  const scenes = project?.scenes || [];
  const failedScene = scenes.find(
    (scene) => scene.scene_status === "failed" || scene.scene_status === "qa_failed",
  );
  const incomplete = qaIncomplete(project?.qa_results?.checks);

  if (status === "failed") {
    const notice = regenerationFailureNotice({
      errorMessage: project?.error_message || "",
      scenes: project?.scenes,
    });
    return {
      key: "failed",
      label: "Video generation failed",
      sara: "Generation stopped before the story was finished.",
      mike:
        merchantError(notice.summary || project?.error_message || "", project?.error_type) ||
        (failedScene
          ? `Scene ${failedScene.order ?? ""} failed.`
          : "The video service did not complete this request."),
    };
  }
  if (status === "correcting") {
    return {
      key: "changes_requested",
      label: "Changes requested",
      sara: "I’m applying your notes to the story.",
      mike: stage || "Updating the affected scenes and rebuilding the video.",
    };
  }
  if (["queued", "analyzing", "brief_ready", "script_ready"].includes(status)) {
    return {
      key: "preparing_story",
      label: "Preparing story",
      sara: stage || "I’m shaping your idea into a story and script.",
      mike: "Format, timing and captions wait until the story is locked.",
    };
  }
  if (status === "planning") {
    return {
      key: "generating_scenes",
      label: "Generating scenes",
      sara: "The story is in place. I’m laying out the scene plan.",
      mike: stage || "Building the scene timeline.",
    };
  }
  if (["generating", "generating_assets", "generating_video"].includes(status)) {
    const current = scenes.find((scene) =>
      ["generating", "regenerating"].includes(scene.scene_status || ""),
    );
    const ready = scenes.filter((scene) =>
      ["generated", "ready", "approved"].includes(scene.scene_status || ""),
    ).length;
    return {
      key: "generating_video",
      label: "Generating video",
      sara: current?.title
        ? `Working through “${current.title}”.`
        : "Generating a continuous film.",
      mike:
        stage ||
        (current
          ? `Updating scene ${current.order}.`
          : "Preparing the film."),
    };
  }
  if (["generating_voice", "processing", "assembling"].includes(status)) {
    return {
      key: "generating_video",
      label: "Generating video",
      sara: "Captions are already on each scene. Production is joining them.",
      mike: stage || "Joining the captioned scenes.",
    };
  }
  if (["qa", "qa_running"].includes(status)) {
    return {
      key: "running_checks",
      label: "Running visual checks",
      sara: "The cut is in review. I won’t mark a check as passed until it actually runs.",
      mike: stage || "Running AI visual and audio checks.",
    };
  }
  if (status === "exported") {
    return {
      key: "approved",
      label: "Approved",
      sara: "This version is approved.",
      mike: project?.export_url || project?.final_url
        ? "The export file is ready to download."
        : "Approved. Export when you want the delivery file.",
    };
  }
  if (status === "approved") {
    return {
      key: "approved",
      label: "Approved",
      sara: "This version is approved.",
      mike: "You can export or start another version.",
    };
  }
  if (status === "ready" || status === "ready_for_review" || project?.preview_url) {
    if (incomplete) {
      return {
        key: "ready_for_review",
        label: "Ready for review",
        sara: "The video is ready to watch. Required checks are still outstanding.",
        mike: "Approval stays blocked until required AI checks complete.",
      };
    }
    return {
      key: "ready_for_review",
      label: "Ready for review",
      sara: scenes.length
        ? `I’ve shaped your idea into ${scenes.length} scene${scenes.length === 1 ? "" : "s"}.`
        : "The video is ready to review.",
      mike: project?.preview_url
        ? "Your 9:16 version is ready. Review it before you approve."
        : "Preview is not available yet.",
    };
  }
  if (project?.selected_concept_id || scenes.length) {
    return {
      key: "ready",
      label: "Ready to generate",
      sara: scenes.length
        ? `I’ve shaped your idea into ${scenes.length} scenes.`
        : "The storyboard is ready when you are.",
      mike: "Generate when the plan looks right. Output is 9:16.",
    };
  }
  if (project?.creative_directions?.some((item) => item.title)) {
    return {
      key: "ready",
      label: "Ready to generate",
      sara: "I’ve drafted three creative directions. Pick the one that fits.",
      mike: "I’ll lock timing, voice and captions after you choose.",
    };
  }
  return {
    key: "ready",
    label: "Ready to generate",
    sara: "Tell me the story you want, and I’ll shape the scenes.",
    mike: "Select a product first. I’ll handle format, voice and captions from there.",
  };
}

export function productionBarWidth(status: string, progress?: number): number {
  if (typeof progress === "number" && progress > 0) {
    return Math.max(0, Math.min(100, progress));
  }
  if (!ACTIVE_STATUSES.has(status)) return 0;
  const index = progressStepIndex(status);
  return Math.round(((index + 1) / PROGRESS_STEPS.length) * 100);
}

export function generationFormatNote(): string {
  return "Generated video is 9:16. Other platforms are delivery preferences only.";
}

export type GenerationTimerMetrics = {
  started_at?: string;
  completed_at?: string;
  total_generation_ms?: number;
  project_creation_started_ms?: number;
  script_generation_started_ms?: number;
};

export type GenerationTimerSource = {
  id?: number;
  status?: string;
  created_at?: string;
  generation_metrics?: GenerationTimerMetrics;
};

export function formatGenerationClock(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function generationStartStorageKey(projectId?: number | string | null): string {
  return projectId ? `misa:video-gen-start:${projectId}` : "";
}

function parseTimeMs(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) return parsed;
    const numeric = Number(value);
    if (Number.isFinite(numeric) && numeric > 0) return numeric;
  }
  return null;
}

export function readStoredGenerationStart(projectId?: number | string | null): number | null {
  if (typeof window === "undefined" || !projectId) return null;
  try {
    const value = Number(window.sessionStorage.getItem(generationStartStorageKey(projectId)) || 0);
    return value > 0 ? value : null;
  } catch {
    return null;
  }
}

export function beginGenerationTimer(projectId?: number | string | null, at = Date.now()): number {
  if (typeof window === "undefined" || !projectId) return at;
  try {
    window.sessionStorage.setItem(generationStartStorageKey(projectId), String(at));
  } catch {
    /* private mode / quota */
  }
  return at;
}

export function rememberGenerationStart(projectId?: number | string | null, startMs = Date.now()): number {
  const existing = readStoredGenerationStart(projectId);
  if (existing) return existing;
  return beginGenerationTimer(projectId, startMs);
}

export function generationStartedAtMs(
  project?: GenerationTimerSource | null,
  fallbackStart?: number | null,
  running = false,
): number | null {
  const metrics = project?.generation_metrics || {};
  const started = parseTimeMs(metrics.started_at);
  const created = parseTimeMs(metrics.project_creation_started_ms);
  const scripted = parseTimeMs(metrics.script_generation_started_ms);
  const completed = parseTimeMs(metrics.completed_at);
  const total = Number(metrics.total_generation_ms || 0);
  const staleBackend = running && (completed != null || total > 0);
  const createdAt = parseTimeMs(project?.created_at);
  let backend = staleBackend ? null : started || created || scripted;
  if (backend != null && createdAt != null && backend + 1000 < createdAt) backend = null;
  const fallback = fallbackStart && fallbackStart > 0 ? fallbackStart : null;
  if (backend && fallback) return Math.min(backend, fallback);
  return backend || fallback || null;
}

export function generationElapsedMs(
  project?: GenerationTimerSource | null,
  now = Date.now(),
  running = false,
  fallbackStart?: number | null,
): number {
  const metrics = project?.generation_metrics || {};
  const start = generationStartedAtMs(project, fallbackStart, running);
  const completed = parseTimeMs(metrics.completed_at);
  if (!running) {
    const total = Number(metrics.total_generation_ms || 0);
    const fromClock = start ? Math.max(0, (completed || now) - start) : 0;
    if (fallbackStart && start === fallbackStart && fromClock > 0) return fromClock;
    if (total > 0) return total;
    return fromClock;
  }
  if (start == null) return 0;
  return Math.max(0, now - start);
}

export function listText(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ");
  return String(value ?? "");
}

export function asStringList(value: string): string[] {
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

export function missingEssentials(values: {
  name: string;
  description: string;
  price: string;
  variants: string;
  dimensions?: string;
  materials?: string;
  approved_claims?: string;
}): string[] {
  const missing: string[] = [];
  if (!values.name.trim()) missing.push("product name");
  if (!values.variants.trim()) missing.push("variant (size or type)");
  if (!values.price.trim()) missing.push("price");
  if (!values.description.trim() && !values.approved_claims?.trim()) {
    missing.push("key facts about the product");
  }
  return missing;
}

export function languageLabel(id: string): string {
  return LANGUAGE_OPTIONS.find((option) => option.id === id)?.label || id;
}

export function styleLabel(id: string): string {
  return STYLE_OPTIONS.find((option) => option.id === id)?.label || id;
}

export function sellStyleLabel(id: string): string {
  return SELL_STYLE_OPTIONS.find((item) => item.id === id)?.label || id;
}

export function genderLabel(id: string): string {
  return GENDER_OPTIONS.find((option) => option.id === id)?.label || id;
}

export function composeSpeakerNote(parts: {
  tone: string;
  gender: string;
  locale: string;
}): string {
  return `Speaker style: ${styleLabel(parts.tone)}, ${genderLabel(parts.gender)}, ${languageLabel(parts.locale)}.`;
}

export function instructionText(value: string): string {
  return value
    .split("\n")
    .filter((line) => {
      const text = line.trim();
      if (!text) return false;
      if (/^Speaker style:/i.test(text)) return false;
      if (/^Selling style:/i.test(text)) return false;
      return !CONTENT_INTENTS.some((intent) => intent.instruction === text);
    })
    .join("\n")
    .trim();
}

export function libraryPosterSrc(item?: { poster_url?: string } | null): string {
  return item?.poster_url || "";
}

export function libraryVideoSrc(item: {
  preview_url?: string;
  final_url?: string;
  export_url?: string;
  scenes?: { order?: number; video_url?: string }[];
}): string {
  const assembled = item.export_url || item.final_url || item.preview_url || "";
  if (assembled) return assembled;
  const clip = [...(item.scenes || [])]
    .filter((scene) => scene.video_url)
    .sort((a, b) => (a.order || 0) - (b.order || 0))[0];
  return clip?.video_url || "";
}

export function isLibraryVideo(item: {
  status: string;
  preview_url?: string;
  final_url?: string;
  export_url?: string;
}): boolean {
  if (item.preview_url || item.final_url || item.export_url) return true;
  return item.status !== "draft";
}

export function historyKind(status: string): string {
  if (status === "draft") return "Draft";
  if (status === "failed") return "Failed";
  if (status === "approved" || status === "exported") return "Approved";
  if (ACTIVE_STATUSES.has(status)) return "In progress";
  return "Generated";
}

export const LIBRARY_PAGE_SIZE = 8;

export const LIBRARY_STATUS_FILTERS = [
  { id: "all", label: "All" },
  { id: "in_progress", label: "In progress" },
  { id: "ready", label: "Ready" },
  { id: "failed", label: "Failed" },
  { id: "approved", label: "Approved" },
] as const;

export type LibraryStatusFilter = (typeof LIBRARY_STATUS_FILTERS)[number]["id"];

export function libraryStatusGroup(status: string): Exclude<LibraryStatusFilter, "all"> {
  if (ACTIVE_STATUSES.has(status)) return "in_progress";
  if (status === "failed") return "failed";
  if (status === "approved" || status === "exported") return "approved";
  return "ready";
}

export function matchesLibraryFilter(
  item: { status: string; product_name?: string; language?: string },
  filter: { query: string; status: LibraryStatusFilter; language: string },
): boolean {
  if (filter.status !== "all" && libraryStatusGroup(item.status) !== filter.status) {
    return false;
  }
  if (filter.language && item.language !== filter.language) return false;
  const query = filter.query.trim().toLowerCase();
  if (query && !(item.product_name || "").toLowerCase().includes(query)) return false;
  return true;
}

export function libraryDownloadName(item: { id?: number; product_name?: string }): string {
  const base =
    (item.product_name || "video")
      .trim()
      .replace(/[/\\?%*:|"<>]+/g, "-")
      .replace(/\s+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 60) || "video";
  return `${base}-${item.id || "file"}.mp4`;
}

export function libraryPageCount(total: number, pageSize = LIBRARY_PAGE_SIZE): number {
  return Math.max(1, Math.ceil(Math.max(total, 0) / pageSize));
}

export function libraryPageItems<T>(items: T[], page: number, pageSize = LIBRARY_PAGE_SIZE): T[] {
  const count = libraryPageCount(items.length, pageSize);
  const current = Math.min(Math.max(page, 1), count);
  const start = (current - 1) * pageSize;
  return items.slice(start, start + pageSize);
}

export function libraryPageNumbers(
  current: number,
  total: number,
): Array<number | "ellipsis"> {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);
  const pages = new Set([1, total, current, current - 1, current + 1]);
  const ordered = [...pages].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b);
  const result: Array<number | "ellipsis"> = [];
  for (const page of ordered) {
    const previous = result[result.length - 1];
    if (typeof previous === "number" && page - previous > 1) result.push("ellipsis");
    result.push(page);
  }
  return result;
}

export function historyLabel(item: {
  status: string;
  created_at?: string;
  merchant_instructions?: string;
}): string {
  const when = item.created_at
    ? new Date(item.created_at).toLocaleString("en-MY", {
        day: "numeric",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";
  const preview = instructionText(item.merchant_instructions || "")
    .replace(/\s+/g, " ")
    .slice(0, 42);
  return [historyKind(item.status), when, preview].filter(Boolean).join(" · ");
}

export function composeInstructions(parts: {
  text: string;
  intent?: string;
  sellStyle?: string;
  tone?: string;
  gender?: string;
  locale?: string;
}): string {
  const lines = [parts.text.trim()].filter(Boolean);
  if (parts.tone || parts.gender || parts.locale) {
    lines.push(
      composeSpeakerNote({
        tone: parts.tone || "warm",
        gender: parts.gender || "female",
        locale: parts.locale || "conversational_bm",
      }),
    );
  }
  const intent = CONTENT_INTENTS.find((item) => item.id === parts.intent);
  if (intent) lines.push(intent.instruction);
  const sell = SELL_STYLE_OPTIONS.find((item) => item.id === parts.sellStyle);
  if (sell) lines.push(`Selling style: ${sell.label}. ${sell.hint}`);
  return lines.join("\n");
}

export const PROVIDER_STATUS_UNAVAILABLE =
  "Video regeneration is currently unavailable. The video provider rejected the status request. Try again after the provider issue is resolved.";

export function merchantError(message: string, errorType?: string): string {
  const type = String(errorType || "").toUpperCase();
  if (type === "RATE_LIMITED" || /rate limited|quota becomes available/i.test(message)) {
    const wait = message.match(/wait\s+([0-9]+h)?([0-9]+m)?([0-9]+s)?/i);
    const retryAfter = wait ? [wait[1], wait[2], wait[3]].filter(Boolean).join("") : "";
    return (
      "Video generation is temporarily rate limited. Please try again when the provider quota becomes available." +
      (retryAfter ? ` The provider asked to wait ${retryAfter}.` : "")
    );
  }
  if (type === "TIMEOUT" || /timed out/i.test(message)) {
    return "Video generation timed out. Please try again.";
  }
  if (type === "PROVIDER_ERROR") {
    return "We couldn't finish the video generation.";
  }
  if (type === "DOWNLOAD_FAILED") {
    return "The generated video could not be downloaded. Please try again.";
  }
  if (type === "MISSING_AUDIO") {
    return "The finished video has no audio. Please try again.";
  }
  if (type === "INVALID_VIDEO") {
    return "The finished video file is not valid. Please try again.";
  }
  if (
    /seedance|gemini|omni|openai|claw|kalodata|byteplus|veo|minimax|nano banana|ffmpeg|model/i.test(
      message,
    )
  ) {
    return "We couldn't finish this just now. Please try again.";
  }
  return message;
}

type FailureScene = {
  failure_code?: string;
  failure_message?: string;
  provider?: string;
  provider_request_id?: string;
  pipeline_error?: {
    detail?: string;
    code?: string;
    provider?: string;
    task_id?: string;
    status?: number;
    error_type?: string;
    retryable?: boolean;
  };
};

export function regenerationFailureNotice(input: {
  errorMessage?: string;
  scenes?: FailureScene[];
}): { summary: string; authentication: boolean } {
  const scenes = input.scenes || [];
  const codes = scenes.map((scene) =>
    String(scene.failure_code || scene.pipeline_error?.code || "").toUpperCase(),
  );
  if (codes.includes("AUTHENTICATION")) {
    return { summary: input.errorMessage || "The video provider rejected authentication.", authentication: true };
  }
  if (codes.includes("INVALID_REQUEST")) {
    return { summary: PROVIDER_STATUS_UNAVAILABLE, authentication: false };
  }
  return { summary: input.errorMessage || "", authentication: false };
}

export function merchantQaDetail(message: string): string {
  return String(message || "")
    .replace(/Seedance audio/gi, "generated audio")
    .replace(/\bStage:\s*(seedance|byteplus|ark|veo|gemini|omni|ffmpeg)\b/gi, "Stage: video generation")
    .replace(/\b(seedance|byteplus|gemini omni)\b/gi, "video generation");
}

export function pipelineStageLabel(stage?: string | null): string {
  const value = String(stage || "").trim().toLowerCase();
  if (!value) return "";
  if (/seedance|byteplus|ark|veo|gemini|omni|video.?generation/.test(value)) {
    return "video generation";
  }
  if (/ffmpeg/.test(value)) {
    return "assembly";
  }
  return value.replace(/_/g, " ");
}

export type QaCheck = {
  name: string;
  status: string;
  detail: string;
  source?: string;
  confidence?: number;
  severity?: string;
  scene_id?: string;
  affected_scenes?: string[];
  timestamp?: number;
  start?: number;
  end?: number;
  frame_url?: string;
  recommended_action?: string;
  qa_category?: string;
  checked?: boolean;
  verified?: boolean;
  stage?: string;
  reason?: string;
};

const QA_GROUPS: { key: string; label: string; names: string[] }[] = [
  { key: "product", label: "Product", names: ["product", "variant", "product_representation", "product_consistency"] },
  { key: "price", label: "Price", names: ["price", "expired_offer"] },
  { key: "claims", label: "Claims", names: ["claims"] },
  { key: "captions", label: "Captions", names: ["captions", "visible_captions"] },
  { key: "audio", label: "Audio", names: ["narration", "pronunciation", "audio_silent", "audio_stream", "assembled_audio"] },
  { key: "presenter", label: "Presenter", names: ["presenter_consistency"] },
];

export function videoCheckSummary(checks: QaCheck[] | undefined): {
  label: string;
  status: "passed" | "warning" | "failed" | "";
}[] {
  return QA_GROUPS.map((group) => {
    const matched = (checks || []).filter((check) =>
      group.names.includes(check.name),
    );
    const statuses = matched.map((check) => check.status);
    const status = statuses.includes("failed")
      ? "failed"
      : statuses.includes("warning")
        ? "warning"
        : matched.length
          ? "passed"
          : "";
    return { label: group.label, status };
  });
}

export type QaMark = "passed" | "warning" | "failed" | "not_checked" | "skipped";

export type QaLayerView = {
  key: string;
  label: string;
  mark: QaMark;
  kind: "verified" | "ai" | "not_checked";
  confidence: number;
  hasConfidence: boolean;
  detail: string;
};

const VISUAL_SOURCES = new Set(["multimodal", "transcription", "OCR"]);

function namedChecks(checks: QaCheck[] | undefined, names: string[]): QaCheck[] {
  return (checks || []).filter((check) => names.includes(check.name));
}

function markFromChecks(items: QaCheck[]): QaMark {
  if (!items.length) return "not_checked";
  if (items.some((check) => check.status === "failed")) return "failed";
  if (items.some((check) => check.status === "warning")) return "warning";
  if (items.some((check) => check.status === "passed")) return "passed";
  if (items.some((check) => check.status === "not_checked")) return "not_checked";
  if (items.some((check) => check.status === "skipped")) return "skipped";
  return "not_checked";
}

function confidenceFromChecks(items: QaCheck[], mark: QaMark): { value: number; show: boolean } {
  if (!["passed", "warning", "failed"].includes(mark)) {
    return { value: 0, show: false };
  }
  const scored = items.filter(
    (check) =>
      ["passed", "warning", "failed"].includes(check.status) &&
      check.checked !== false &&
      typeof check.confidence === "number" &&
      !Number.isNaN(check.confidence),
  );
  if (!scored.length) return { value: 0, show: false };
  return { value: Math.max(...scored.map((check) => Number(check.confidence))), show: true };
}

function makeCard(
  key: string,
  label: string,
  items: QaCheck[],
  fallback: { detail: string; kind?: QaLayerView["kind"] },
): QaLayerView {
  const mark = markFromChecks(items);
  const confidence = confidenceFromChecks(items, mark);
  const first = items.find((check) => check.status === mark) || items[0];
  const kind: QaLayerView["kind"] =
    mark === "not_checked" || mark === "skipped"
      ? "not_checked"
      : fallback.kind ||
        (VISUAL_SOURCES.has(first?.source || "") || first?.name?.includes("visual") ? "ai" : "verified");
  return {
    key,
    label,
    mark,
    kind,
    confidence: confidence.value,
    hasConfidence: confidence.show,
    detail: first?.detail || fallback.detail,
  };
}

function cardFromLayer(
  key: string,
  label: string,
  side: { status?: string; detail?: string; confidence?: number; source?: string } | undefined,
  fallbackDetail: string,
): QaLayerView {
  const mark = (side?.status || "not_checked") as QaMark;
  const ran = mark === "passed" || mark === "warning" || mark === "failed";
  const hasConfidence =
    ran && typeof side?.confidence === "number" && !Number.isNaN(side.confidence);
  return {
    key,
    label,
    mark,
    kind: mark === "not_checked" || mark === "skipped" ? "not_checked" : side?.source ? "ai" : "verified",
    confidence: hasConfidence ? Number(side?.confidence) : 0,
    hasConfidence,
    detail: side?.detail || fallbackDetail,
  };
}

export function qaLayerSummary(
  layers:
    | Record<string, { structural?: { status?: string; detail?: string }; visual?: { status?: string; confidence?: number; source?: string; detail?: string } }>
    | undefined,
  checks?: QaCheck[],
): QaLayerView[] {
  if (checks?.length) {
    const productStruct = namedChecks(checks, [
      "product",
      "variant",
      "claims",
      "product_representation",
      "product_consistency",
    ]).filter((check) => !VISUAL_SOURCES.has(check.source || ""));
    const productVisual = namedChecks(checks, ["product_visual_consistency", "product_component"]);
    const presenterLock = namedChecks(checks, ["presenter_consistency"]).filter(
      (check) => !VISUAL_SOURCES.has(check.source || ""),
    );
    const presenterVisual = namedChecks(checks, [
      "presenter_visual_consistency",
      "presenter_continuity",
    ]);
    const scenes = namedChecks(checks, ["scene_completeness", "video_generation", "scene_variety"]);
    const offer = namedChecks(checks, ["price", "expired_offer", "cta_complete"]);
    const captions = namedChecks(checks, ["captions", "visible_captions", "caption_lines"]).filter(
      (check) => !VISUAL_SOURCES.has(check.source || ""),
    );
    const narration = namedChecks(checks, ["narration"]);
    const audioOut = namedChecks(checks, [
      "audio_silent",
      "audio_stream",
      "audio_duration",
      "assembled_audio",
    ]);
    const language = namedChecks(checks, ["ai_review", "malay_copy"]);
    return [
      makeCard("product", "Product accuracy", productStruct, {
        detail: "Product information/claims match the product record.",
        kind: "verified",
      }),
      makeCard("product_visual", "Product visual match", productVisual, {
        detail: "Original product photos were not compared with the generated video.",
        kind: "ai",
      }),
      makeCard("presenter", "Presenter lock", presenterLock, {
        detail: "Presenter lock was not checked.",
        kind: "verified",
      }),
      makeCard("presenter_visual", "Presenter visual identity", presenterVisual, {
        detail: "Presenter visual identity was not checked against a photo.",
        kind: "ai",
      }),
      makeCard("character", "Character consistency", namedChecks(checks, ["character_consistency"]), {
        detail: "Character consistency was not compared with the reference images in this run.",
        kind: "ai",
      }),
      makeCard("scene", "Scenes complete", scenes, { detail: "Scene completeness was not checked." }),
      makeCard("offer", "Offer/price", offer, { detail: "Offer and price were not checked." }),
      makeCard("caption", "Captions", captions, { detail: "Captions were not checked." }),
      makeCard("narration", "Narration present", narration, {
        detail: "Narration text was not checked.",
        kind: "verified",
      }),
      makeCard("audio", "Audio output", audioOut, {
        detail: "Generated audio was not inspected.",
        kind: "verified",
      }),
      ...(language.length
        ? [
            makeCard("language", "Language review", language, {
              detail: "Automated language review was unavailable.",
            }),
          ]
        : []),
      visualQaRollup(checks),
    ];
  }

  if (!layers || !Object.keys(layers).length) {
    return [
      {
        key: "visual",
        label: "Visual QA",
        mark: "not_checked",
        kind: "not_checked",
        confidence: 0,
        hasConfidence: false,
        detail: "Product photo comparison was not completed.",
      },
    ];
  }

  return [
    cardFromLayer(
      "product",
      "Product accuracy",
      layers.product?.structural,
      "Product information/claims match the product record.",
    ),
    cardFromLayer(
      "product_visual",
      "Product visual match",
      layers.product?.visual,
      "Original product photos were not compared with the generated video.",
    ),
    cardFromLayer("presenter", "Presenter lock", layers.presenter?.structural, "Presenter lock was not checked."),
    cardFromLayer(
      "presenter_visual",
      "Presenter visual identity",
      layers.presenter?.visual,
      "Presenter visual identity was not checked against a photo.",
    ),
    cardFromLayer("scene", "Scenes complete", layers.scene?.structural, "Scene completeness was not checked."),
    cardFromLayer("offer", "Offer/price", layers.offer?.structural, "Offer and price were not checked."),
    cardFromLayer("caption", "Captions", layers.caption?.structural, "Captions were not checked."),
    cardFromLayer("narration", "Narration present", layers.audio?.structural, "Narration text was not checked."),
    cardFromLayer("audio", "Audio output", undefined, "Generated audio was not inspected."),
    visualQaRollup([]),
  ];
}

export function visualQaRollup(checks: QaCheck[] | undefined): QaLayerView {
  const unchecked: QaLayerView = {
    key: "visual",
    label: "Visual QA",
    mark: "not_checked",
    kind: "not_checked",
    confidence: 0,
    hasConfidence: false,
    detail: "No confidence available because the visual comparison did not run.",
  };
  const productVisual = (checks || []).find((check) => check.name === "product_visual_consistency");
  const visual = (checks || []).filter(
    (check) =>
      VISUAL_SOURCES.has(check.source || "") ||
      ["product_visual_consistency", "product_component", "caption_visual"].includes(check.name),
  );
  const ran = visual.filter((check) => ["passed", "warning", "failed"].includes(check.status));
  const failed = ran.filter((check) => check.status === "failed");
  const warning = ran.filter((check) => check.status === "warning");
  const productIncomplete =
    !productVisual || productVisual.status === "not_checked" || productVisual.status === "skipped";

  if (failed.length) {
    const confidence = confidenceFromChecks(failed, "failed");
    return {
      key: "visual",
      label: "Visual QA",
      mark: "failed",
      kind: "ai",
      confidence: confidence.value,
      hasConfidence: confidence.show,
      detail: `${failed.length} serious visual issue${failed.length === 1 ? "" : "s"}`,
    };
  }
  if (productIncomplete) {
    return {
      ...unchecked,
      mark: productVisual?.status === "skipped" ? "skipped" : "not_checked",
      detail:
        productVisual?.detail ||
        "No confidence available because the visual comparison did not run.",
    };
  }
  if (warning.length) {
    const confidence = confidenceFromChecks(warning, "warning");
    return {
      key: "visual",
      label: "Visual QA",
      mark: "warning",
      kind: "ai",
      confidence: confidence.value,
      hasConfidence: confidence.show,
      detail: `${warning.length} warning${warning.length === 1 ? "" : "s"}`,
    };
  }
  if (!ran.length) {
    return unchecked;
  }
  const confidence = confidenceFromChecks(ran, "passed");
  return {
    key: "visual",
    label: "Visual QA",
    mark: "passed",
    kind: "ai",
    confidence: confidence.value,
    hasConfidence: confidence.show,
    detail: "Visual comparison passed",
  };
}

export function qaCardDetail(item: QaLayerView): string {
  const detail = merchantQaDetail(item.detail || "");
  if (item.mark === "not_checked" || item.mark === "skipped") {
    return detail || "Not checked";
  }
  if (item.hasConfidence && item.kind === "ai") {
    return `${detail}${detail.endsWith(".") ? "" : "."} ${Math.round(item.confidence * 100)}% confidence`;
  }
  return detail;
}

const RELEASE_BLOCKING = new Set([
  "character_identity",
  "scene_narration",
  "audio_silent",
  "audio_stream",
  "audio_duration",
  "assembled_audio",
  "product_visual_consistency",
  "product_component",
  "caption_visual",
  "caption_lines",
  "claims",
  "cta_complete",
  "expired_offer",
]);

export function qaIssueCards(checks: QaCheck[] | undefined): QaCheck[] {
  return (checks || []).filter(
    (check) =>
      (check.status === "failed" || check.status === "warning") &&
      check.name !== "ai_review",
  );
}

export function qaNeedsRerun(checks: QaCheck[] | undefined): boolean {
  return (checks || []).some((check) => {
    if (check.name === "ai_review" && ["warning", "not_checked", "skipped", "failed"].includes(check.status)) {
      return true;
    }
    return (
      (check.status === "not_checked" || check.status === "skipped") &&
      (RELEASE_BLOCKING.has(check.name) || check.name === "product_visual_consistency")
    );
  });
}

export function qaIncomplete(checks: QaCheck[] | undefined): boolean {
  return (checks || []).some(
    (check) =>
      (check.status === "not_checked" || check.status === "skipped") &&
      (RELEASE_BLOCKING.has(check.name) ||
        check.name === "ai_review" ||
        check.name === "product_visual_consistency"),
  );
}

export function seriousQaIssues(checks: QaCheck[] | undefined): QaCheck[] {
  return (checks || []).filter(
    (check) =>
      ["failed", "warning"].includes(check.status) &&
      ["multimodal", "transcription", "OCR"].includes(check.source || "") &&
      Number(check.confidence || 0) >= 0.85 &&
      ["high", "critical"].includes(check.severity || ""),
  );
}

export function releaseBlockingIssues(
  checks: QaCheck[] | undefined,
  options?: { hasPreview?: boolean },
): QaCheck[] {
  const hasPreview = options?.hasPreview !== false;
  return (checks || []).filter((check) => {
    if (!RELEASE_BLOCKING.has(check.name)) return false;
    if (check.status === "failed") return true;
    if (check.status === "not_checked" || check.status === "skipped") {
      if (check.name === "product_visual_consistency") return hasPreview;
      return [
        "character_identity",
        "scene_narration",
        "audio_silent",
        "audio_stream",
        "assembled_audio",
        "cta_complete",
        "claims",
      ].includes(check.name);
    }
    return (
      check.name === "caption_visual" &&
      check.status === "warning" &&
      /cover/i.test(check.detail || "") &&
      Number(check.confidence || 0) >= 0.85
    );
  });
}

export function qaStatusLabel(status: string): string {
  if (status === "passed") return "PASS";
  if (status === "warning") return "WARNING";
  if (status === "failed") return "FAIL";
  if (status === "skipped") return "SKIPPED";
  return "NOT CHECKED";
}

export function confidenceLabel(check: QaCheck): string {
  if (check.status === "not_checked") return "Not checked";
  if (check.status === "skipped") return "Skipped";
  if (check.name === "ai_review") return "AI language review";
  const ran = check.status === "passed" || check.status === "warning" || check.status === "failed";
  const hasScore =
    ran &&
    check.checked !== false &&
    typeof check.confidence === "number" &&
    !Number.isNaN(check.confidence);
  if (
    hasScore &&
    (check.source === "multimodal" || check.source === "transcription" || check.source === "OCR")
  ) {
    const value = Number(check.confidence);
    if (value >= 0.85) return "High confidence";
    if (value >= 0.6) return "Medium confidence";
    return "Low confidence";
  }
  if (check.verified) return "Verified";
  if (check.source === "structural" || check.verified === false && !VISUAL_SOURCES.has(check.source || "")) {
    return check.source === "provider" ? "AI language review" : "Checked in the script";
  }
  return "Checked in the script";
}

export function plainQaIssue(checks: QaCheck[] | undefined): string {
  const problem = (checks || []).find(
    (check) => check.status === "failed" || check.status === "warning",
  );
  return problem?.detail || "";
}

export function usageCredits(
  records: { project?: number | null }[],
  projectId?: number | null,
): { video: number; account: number } {
  return {
    video: records.filter((row) => projectId && row.project === projectId).length,
    account: records.length,
  };
}
