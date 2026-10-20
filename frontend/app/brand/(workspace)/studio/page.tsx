"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { ApprovalControls } from "@/components/studio/ApprovalControls";
import { BriefRail } from "@/components/studio/BriefRail";
import { BulkGenerationProgress } from "@/components/studio/BulkGenerationProgress";
import { ConceptCards } from "@/components/studio/ConceptCards";
import { CreativeBriefWizard } from "@/components/studio/CreativeBriefWizard";
import { DirectorNotes } from "@/components/studio/DirectorNotes";
import { GenerationProgress } from "@/components/studio/GenerationProgress";
import { ProductionHeader } from "@/components/studio/ProductionHeader";
import { SceneEditor } from "@/components/studio/SceneEditor";
import { StoryboardTimeline } from "@/components/studio/StoryboardTimeline";
import { VideoReview } from "@/components/studio/VideoReview";
import { PrimaryButton, SecondaryButton } from "@/components/studio/ui";
import { StudioProductModal } from "@/components/brand/StudioProductModal";
import {
  api,
  endpoints,
  type Brand,
  type Category,
  type Product,
  type StudioScene,
  type StudioCharacter,
  type UsageRecord,
  type VideoProject,
  type VoiceOption,
  type VideoStatus,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  briefFromProject,
  canVisitStudioStep,
  conceptCreateChecks,
  conceptsFrom,
  directorResumeStep,
  emptyBrief,
  presenterPayload,
  type CreativeBriefForm,
} from "@/lib/director";
import {
  ACTIVE_STATUSES,
  GENDER_OPTIONS,
  LANGUAGE_OPTIONS,
  STUDIO_STEPS,
  STYLE_OPTIONS,
  beginGenerationTimer,
  expandStudioBulkJobs,
  genderLabel,
  historyLabel,
  languageLabel,
  merchantError,
  previousStep,
  productionPhase,
  qaNeedsRerun,
  reviewStepForStatus,
  styleLabel,
  usageCredits,
  type BulkDurationMode,
  type BulkGenderMode,
  type StudioStepId,
} from "@/lib/studio";
import {
  clearHomeDraft,
  draftToBriefSeed,
  hasHomeDraft,
  readHomeDraft,
} from "@/lib/home";
import { applyCharacterDefaults, characterIsVideoReady, MASTER_REQUIRED_MESSAGE } from "@/lib/characters";

const NEW_PRODUCT = "__new__";

export default function AiStudioPage() {
  const { token } = useAuth();
  const [step, setStep] = useState<StudioStepId>("compose");
  const [products, setProducts] = useState<Product[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [brandId, setBrandId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [productId, setProductId] = useState<number | null>(null);
  const [showProductModal, setShowProductModal] = useState(false);
  const [videos, setVideos] = useState<VideoProject[]>([]);
  const [historyId, setHistoryId] = useState("");
  const [characters, setCharacters] = useState<StudioCharacter[]>([]);
  const [voices, setVoices] = useState<VoiceOption[]>([]);
  const [characterId, setCharacterId] = useState("");
  const [generateCharacter, setGenerateCharacter] = useState(false);
  const [voiceId, setVoiceId] = useState("");
  const [characterNote, setCharacterNote] = useState("");
  const [language, setLanguage] = useState("conversational_bm");
  const [style, setStyle] = useState("warm");
  const [gender, setGender] = useState("female");
  const [brief, setBrief] = useState<CreativeBriefForm>(emptyBrief());
  const [project, setProject] = useState<VideoProject | null>(null);
  const [editingScene, setEditingScene] = useState<StudioScene | null>(null);
  const [mixing, setMixing] = useState(false);
  const [mixKeys, setMixKeys] = useState<string[]>([]);
  const [correction, setCorrection] = useState("");
  const [correctionVoice, setCorrectionVoice] = useState<File | null>(null);
  const [showCorrection, setShowCorrection] = useState(false);
  const [usage, setUsage] = useState<UsageRecord[]>([]);
  const [publishPlatform, setPublishPlatform] = useState("");
  const [publishAuthorized, setPublishAuthorized] = useState(false);
  const [publishNote, setPublishNote] = useState("");
  const [error, setError] = useState("");
  const [draftNote, setDraftNote] = useState("");
  const [pending, setPending] = useState(false);
  const [pendingFast, setPendingFast] = useState(false);
  const [savingDraft, setSavingDraft] = useState(false);
  const [selectedSceneKey, setSelectedSceneKey] = useState<string | null>(null);
  const [selectedConceptIds, setSelectedConceptIds] = useState<string[]>([]);
  const [bulkCharacterIds, setBulkCharacterIds] = useState<string[]>([]);
  const [bulkGenerateCharacter, setBulkGenerateCharacter] = useState(false);
  const [bulkGenderMode, setBulkGenderMode] = useState<BulkGenderMode>("female");
  const [bulkDurationMode, setBulkDurationMode] = useState<BulkDurationMode>("fixed");
  const [bulkCount, setBulkCount] = useState(0);
  const [bulkProjects, setBulkProjects] = useState<VideoProject[]>([]);
  const bulkModeRef = useRef(false);

  const product = products.find((item) => item.id === productId) || null;
  const selectedCharacter = characters.find((item) => String(item.id) === characterId) || null;
  const generating = Boolean(
    (project && ACTIVE_STATUSES.has(project.status)) ||
      bulkProjects.some((item) => ACTIVE_STATUSES.has(item.status)),
  );
  const credits = usageCredits(usage, project?.id);
  const approved = project?.status === "approved" || project?.status === "exported";
  const currentIndex = STUDIO_STEPS.findIndex((item) => item.id === step);
  const concepts = conceptsFrom(project);
  const bulkPreview = expandStudioBulkJobs({
    conceptIds: selectedConceptIds,
    characterIds: bulkCharacterIds,
    generateCharacter: bulkGenerateCharacter,
    genderMode: bulkGenderMode,
    durationMode: bulkDurationMode,
    durationSeconds: brief.duration || project?.duration_seconds || 45,
    count: bulkCount || undefined,
  });
  const bulkVideoCount = bulkPreview.jobs.length || bulkPreview.combinationCount;
  const conceptChecks = conceptCreateChecks({
    hasProduct: Boolean(product),
    objective: brief.objective,
    customer: brief.customer,
    mainBenefit: brief.main_benefit,
    generateCharacter,
    hasCharacter: Boolean(selectedCharacter),
    characterReady: Boolean(selectedCharacter && characterIsVideoReady(selectedCharacter)),
  });
  const conceptGaps = conceptChecks.filter((item) => !item.ready);
  const canCreateConcepts = conceptGaps.length === 0;

  const productHistory = useMemo(
    () => (productId ? videos.filter((item) => item.product === productId) : []),
    [videos, productId],
  );
  const filteredBrands = useMemo(
    () => (categoryId ? brands.filter((brand) => String(brand.category) === categoryId) : brands),
    [brands, categoryId],
  );
  const filteredProducts = useMemo(
    () =>
      products.filter((item) => {
        if (brandId && String(item.brand) !== brandId) return false;
        if (categoryId && String(item.category) !== categoryId) return false;
        return true;
      }),
    [products, brandId, categoryId],
  );
  const characterChoices = useMemo(() => {
    const matching = characters.filter((item) => {
      if (product) return Number(item.brand) === Number(product.brand);
      if (brandId) return Number(item.brand) === Number(brandId);
      return true;
    });
    return matching.length ? matching : characters;
  }, [characters, product, brandId]);

  useEffect(() => {
    const ids = concepts.map((item) => item.id).filter(Boolean);
    setSelectedConceptIds((current) => {
      const still = current.filter((id) => ids.includes(id));
      return still.length ? still : ids;
    });
  }, [concepts.map((item) => item.id).join(",")]);

  useEffect(() => {
    const readyIds = new Set(
      characters.filter((item) => characterIsVideoReady(item)).map((item) => String(item.id)),
    );
    if (characterId && readyIds.has(characterId) && !generateCharacter) {
      setBulkCharacterIds((current) => (current.includes(characterId) ? current : [characterId, ...current]));
    }
    if (generateCharacter) {
      setBulkGenerateCharacter(true);
      setBulkCharacterIds((current) => current.filter((id) => readyIds.has(id)));
    }
    if (gender === "male" || gender === "female") setBulkGenderMode(gender);
  }, [characterId, characters, generateCharacter, gender]);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      api<Product[]>(endpoints.brands.products, { token }),
      api<Brand[]>(endpoints.brands.list, { token }),
      api<Category[]>(endpoints.brands.categories, { token }),
      api<{ language: string; speaking_style: string; speaker_gender?: string }>(
        endpoints.ai.preferences,
        { token },
      ).catch(() => null),
      api<VideoProject[]>(endpoints.ai.videos, { token }).catch(() => []),
      api<StudioCharacter[]>(endpoints.ai.characters, { token }).catch(() => []),
      api<VoiceOption[]>(endpoints.ai.voices, { token }).catch(() => []),
    ]).then(async ([nextProducts, nextBrands, nextCategories, prefs, nextVideos, nextCharacters, nextVoices]) => {
      setProducts(nextProducts);
      setBrands(nextBrands);
      setCategories(nextCategories);
      setVideos(nextVideos);
      setCharacters(nextCharacters || []);
      setVoices(nextVoices || []);
      if (prefs) {
        setLanguage(prefs.language);
        setStyle(prefs.speaking_style);
        if (prefs.speaker_gender) setGender(prefs.speaker_gender);
      }
      const requestedId = new URLSearchParams(window.location.search).get("project");
      const requestedStep = new URLSearchParams(window.location.search).get("step");
      const requestedProject = requestedId
        ? nextVideos.find((item) => String(item.id) === requestedId)
        : undefined;
      const hydrate = async (item?: VideoProject) => {
        if (!item?.id || item.scenes) return item;
        try {
          const full = await api<VideoProject>(endpoints.ai.videoDetail(item.id), { token });
          setVideos((current) => current.map((row) => (row.id === full.id ? full : row)));
          return full;
        } catch {
          return item;
        }
      };
      if (requestedProject) {
        const full = (await hydrate(requestedProject)) || requestedProject;
        applyProject(full, nextProducts);
        const nextStep =
          requestedStep && canVisitStudioStep(requestedStep, full)
            ? (requestedStep as StudioStepId)
            : reviewStepForStatus(full.status);
        setStep(nextStep);
      } else {
      const active = nextVideos
        .filter((item) => ACTIVE_STATUSES.has(item.status))
        .sort((a, b) => {
          const later = Date.parse(b.updated_at || b.created_at || "") || 0;
          const earlier = Date.parse(a.updated_at || a.created_at || "") || 0;
          if (later !== earlier) return later - earlier;
          return (b.id || 0) - (a.id || 0);
        })[0];
      if (active) {
        const full = (await hydrate(active)) || active;
        applyProject(full, nextProducts);
        setStep(reviewStepForStatus(full.status));
      } else {
        const draft = readHomeDraft();
        if (hasHomeDraft(draft) && draft) {
          const seed = draftToBriefSeed(draft);
          setBrief({
            ...emptyBrief(seed.duration),
            objective: seed.objective,
            customer: seed.customer,
            main_benefit: seed.main_benefit,
            duration: seed.duration,
            platform: seed.platform,
            legacy_instructions: seed.prompt,
            must_remain_exact: seed.must_remain_exact,
          });
          setDraftNote("Your homepage idea is ready. Choose or add a product, then continue.");
          setStep("compose");
          clearHomeDraft();
        }
        const requested = new URLSearchParams(window.location.search).get("character");
        const requestedCharacter = (nextCharacters || []).find((item) => String(item.id) === requested);
        if (requestedCharacter) {
          if (characterIsVideoReady(requestedCharacter)) chooseCharacter(requestedCharacter);
          else {
            setCharacterNote(MASTER_REQUIRED_MESSAGE);
          }
        }
      }
      }
    });
    api<{ results: UsageRecord[] }>(endpoints.ai.usage, { token })
      .then((data) => setUsage(data.results || []))
      .catch(() => setUsage([]));
  }, [token]);

  useEffect(() => {
    if (!token || !project || !ACTIVE_STATUSES.has(project.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const status = await api<VideoStatus>(endpoints.ai.videoStatus(project.id), { token });
        if (status.status === "failed") {
          setProject({
            ...project,
            ...status,
            scenes: mergeSceneStatus(project.scenes, status.scene_statuses),
          });
          setBulkProjects((current) =>
            current.map((item) => (item.id === project.id ? { ...item, ...status } : item)),
          );
          if (!bulkModeRef.current) {
            setError(merchantError(status.error_message || "We couldn't finish this video.", status.error_type));
          }
          setStep("generate");
          return;
        }
        if (!ACTIVE_STATUSES.has(status.status)) {
          const full = await api<VideoProject>(endpoints.ai.videoDetail(project.id), { token });
          setProject(full);
          setBulkProjects((current) => current.map((item) => (item.id === full.id ? full : item)));
          if (bulkModeRef.current) return;
          setShowCorrection(false);
          setStep("review");
          return;
        }
        if (status.preview_url && !project.preview_url) {
          const full = await api<VideoProject>(endpoints.ai.videoDetail(project.id), { token });
          setProject({
            ...full,
            ...status,
            scenes: mergeSceneStatus(full.scenes, status.scene_statuses),
          });
          setBulkProjects((current) => current.map((item) => (item.id === full.id ? { ...full, ...status } : item)));
          return;
        }
        setProject({
          ...project,
          ...status,
          scenes: mergeSceneStatus(project.scenes, status.scene_statuses),
        });
        setBulkProjects((current) =>
          current.map((item) => (item.id === project.id ? { ...item, ...status } : item)),
        );
      } catch {
        // Keep polling; a single failed status check should not stop the run.
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [token, project]);

  useEffect(() => {
    if (!token || bulkProjects.length < 2) return;
    const ids = bulkProjects.filter((item) => ACTIVE_STATUSES.has(item.status) && item.id !== project?.id).map((item) => item.id);
    if (!ids.length) return;
    const timer = window.setInterval(async () => {
      const rows = await Promise.all(
        ids.map(async (id) => {
          try {
            return await api<VideoStatus>(endpoints.ai.videoStatus(id), { token });
          } catch {
            return null;
          }
        }),
      );
      setBulkProjects((current) =>
        current.map((item) => {
          const status = rows.find((row) => row && row.id === item.id);
          return status ? { ...item, ...status } : item;
        }),
      );
    }, 2500);
    return () => window.clearInterval(timer);
  }, [token, project?.id, bulkProjects.map((item) => `${item.id}:${item.status}`).join(",")]);

  function applyProject(item: VideoProject, catalog: Product[] = products) {
    setProject(item);
    setProductId(item.product);
    const match = catalog.find((row) => row.id === item.product);
    if (match) {
      setBrandId(String(match.brand));
      setCategoryId(String(match.category));
    }
    setLanguage(item.language);
    setStyle(item.speaking_style);
    if (item.speaker_gender) setGender(item.speaker_gender);
    setBrief(briefFromProject(item, match || product));
    if (item.character_config?.character) {
      setCharacterId(String(item.character_config.character));
      setVoiceId(item.character_config.voice_id || "");
      setGenerateCharacter(false);
    } else {
      setGenerateCharacter(Boolean((item.creative_brief || {}).generate_character));
    }
  }

  function chooseCharacter(character: StudioCharacter | null) {
    if (!character) {
      setCharacterId("");
      setCharacterNote("");
      return;
    }
    setGenerateCharacter(false);
    if (!characterIsVideoReady(character)) {
      setCharacterId(String(character.id));
      setCharacterNote(MASTER_REQUIRED_MESSAGE);
      return;
    }
    const next = applyCharacterDefaults(
      { language, style, gender, voiceId, voiceProvider: "google_tts", voiceName: "" },
      character,
    );
    setCharacterId(String(character.id));
    setLanguage(next.language);
    setStyle(next.style);
    setGender(next.gender);
    setVoiceId(next.voiceId);
    setBrief((current) => ({
      ...current,
      presenter_look: character.appearance_description || current.presenter_look,
    }));
    setCharacterNote(`${character.name} loaded. Language, tone, gender, and voice can change for this video only.`);
  }

  function keepProject(next: VideoProject) {
    setProject(next);
    setVideos((current) => [next, ...current.filter((item) => item.id !== next.id)]);
    if (typeof window !== "undefined" && next?.id) {
      const url = new URL(window.location.href);
      url.searchParams.set("project", String(next.id));
      window.history.replaceState({}, "", url.toString());
      try {
        sessionStorage.setItem(`videoProject:${next.id}`, JSON.stringify({ id: next.id, step }));
      } catch {
        /* ignore quota */
      }
    }
  }

  function go(next: StudioStepId, nextProject: VideoProject | null = project) {
    if (!canVisitStudioStep(next, nextProject) && next !== "compose") {
      setError(
        next === "generate"
          ? "Choose a concept and review the storyboard before generating."
          : "Finish the previous director step first.",
      );
      return;
    }
    setError("");
    setStep(next);
  }

  function selectBrand(nextBrand: string) {
    setBrandId(nextBrand);
    const brand = brands.find((item) => String(item.id) === nextBrand);
    if (brand) setCategoryId(String(brand.category));
    const stillValid = products.find(
      (item) =>
        item.id === productId &&
        String(item.brand) === nextBrand &&
        (!brand || String(item.category) === String(brand.category)),
    );
    if (!stillValid) {
      setProductId(null);
      setHistoryId("");
    }
  }

  function selectCategory(nextCategory: string) {
    setCategoryId(nextCategory);
    const brand = brands.find((item) => String(item.id) === brandId);
    if (brand && nextCategory && String(brand.category) !== nextCategory) {
      setBrandId("");
    }
    if (product && nextCategory && String(product.category) !== nextCategory) {
      setProductId(null);
      setHistoryId("");
    }
  }

  function selectProduct(value: string) {
    if (value === NEW_PRODUCT) {
      setShowProductModal(true);
      return;
    }
    const nextId = value ? Number(value) : null;
    setProductId(nextId);
    setHistoryId("");
    const next = products.find((item) => item.id === nextId);
    if (next) {
      setBrandId(String(next.brand));
      setCategoryId(String(next.category));
      setBrief((current) => ({
        ...emptyBrief(current.duration),
        original_price: next.price || "",
        offer_text: next.offer || "",
        duration: current.duration,
      }));
    }
    setDraftNote("");
    setProject(null);
  }

  function selectHistory(value: string) {
    if (!value) {
      setHistoryId("");
      setProject(null);
      if (product) {
        setBrief((current) => ({
          ...emptyBrief(current.duration),
          original_price: product.price || "",
          offer_text: product.offer || "",
        }));
      }
      return;
    }
    const row = videos.find((item) => String(item.id) === value);
    if (!row) return;
    setHistoryId(String(row.id));
    const open = async () => {
      let item = row;
      if (!item.scenes && token) {
        try {
          item = await api<VideoProject>(endpoints.ai.videoDetail(item.id), { token });
          setVideos((current) => current.map((entry) => (entry.id === item.id ? item : entry)));
        } catch {
          /* use the library row */
        }
      }
      applyProject(item);
      const resume = directorResumeStep(item) || reviewStepForStatus(item.status);
      setStep(resume);
    };
    void open();
    setDraftNote("");
    setError("");
  }

  function resetCompose() {
    setProject(null);
    setError("");
    setDraftNote("");
    setStep("compose");
    setShowCorrection(false);
    setEditingScene(null);
    setMixing(false);
    setMixKeys([]);
  }

  function studioFields(target = new FormData()) {
    if (!product) return null;
    target.append("product_id", String(product.id));
    target.append("name", product.name);
    target.append("description", product.description);
    target.append("price", brief.original_price || product.price);
    target.append("variants", JSON.stringify(product.variants || []));
    target.append("dimensions", product.dimensions || "");
    target.append("materials", product.materials || "");
    target.append("offer", brief.offer_text || product.offer || "");
    target.append("offer_expiry", product.offer_expiry || "");
    target.append("approved_claims", JSON.stringify(product.approved_claims || []));
    target.append("prohibited_claims", JSON.stringify(product.prohibited_claims || []));
    target.append("language", language);
    target.append("style", style);
    target.append("gender", gender);
    target.append("duration_seconds", String(brief.duration));
    const presenter = presenterPayload(brief, gender);
    target.append(
      "creative_brief",
      JSON.stringify({
        ...brief,
        location: brief.location,
        presenter: {
          ...presenter,
          mode: generateCharacter ? "generated" : characterId ? "character" : presenter.ethnicity || presenter.look ? "generated" : "",
        },
        character_id: generateCharacter ? null : characterId ? Number(characterId) : null,
        generate_character: generateCharacter,
      }),
    );
    target.append("character_id", generateCharacter ? "" : characterId || "");
    if (brief.legacy_instructions.trim()) target.append("instructions", brief.legacy_instructions.trim());
    if (voiceId) target.append("voice_id", voiceId);
    const selected = videos.find((item) => String(item.id) === historyId);
    if (project?.id) target.append("project_id", String(project.id));
    else if (selected?.status === "draft") target.append("draft_id", String(selected.id));
    else if (selected) target.append("source_id", String(selected.id));
    return target;
  }

  async function saveBrief() {
    if (!token || !product) return null;
    const payload = studioFields();
    if (!payload) return null;
    payload.append("objective", brief.objective);
    payload.append("customer", brief.customer);
    payload.append("main_benefit", brief.main_benefit);
    payload.append("original_price", brief.original_price);
    payload.append("offer_price", brief.offer_price);
    payload.append("offer_text", brief.offer_text);
    const saved = await api<VideoProject>(endpoints.ai.videoBrief, {
      method: "POST",
      token,
      body: payload,
    });
    keepProject(saved);
    setHistoryId(String(saved.id));
    return saved;
  }

  async function onSaveDraft() {
    if (!token || !product) return;
    setError("");
    setSavingDraft(true);
    try {
      const saved = await saveBrief();
      if (saved) setDraftNote("Draft saved. You can reopen it from previous versions.");
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to save draft."));
    } finally {
      setSavingDraft(false);
    }
  }

  async function onCreateConcepts(event?: FormEvent, count?: number) {
    event?.preventDefault();
    if (!token || !product) {
      setError(conceptGaps[0]?.hint || "Select a product to continue.");
      return;
    }
    if (!canCreateConcepts) {
      setError(conceptGaps.map((item) => item.hint).join(" "));
      return;
    }
    const conceptCount =
      count ||
      (step === "concepts"
        ? Math.min(10, Math.max(1, bulkCount || bulkPreview.combinationCount || concepts.length || 3))
        : 3);
    setError("");
    setPending(true);
    try {
      const saved = await saveBrief();
      if (!saved) return;
      const created = await api<VideoProject>(endpoints.ai.videoProjectConcepts(saved.id), {
        method: "POST",
        token,
        body: JSON.stringify({
          count: conceptCount,
          creative_brief: {
            ...brief,
            location: brief.location,
            presenter: presenterPayload(brief, gender),
            character_id: generateCharacter ? null : characterId ? Number(characterId) : null,
            generate_character: generateCharacter,
          },
        }),
      });
      keepProject(created);
      setSelectedConceptIds((created.creative_directions || []).map((item) => item.id).filter(Boolean));
      go("concepts", created);
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to create concepts."));
    } finally {
      setPending(false);
    }
  }

  async function onUseConcept(conceptId: string, sceneMix?: { concept_id: string; scene_key: string }[]) {
    if (!token || !project) return;
    setPending(true);
    setError("");
    try {
      const updated = await api<VideoProject>(endpoints.ai.videoSelectConcept(project.id), {
        method: "POST",
        token,
        body: JSON.stringify({ concept_id: conceptId, scene_mix: sceneMix }),
      });
      keepProject(updated);
      setMixing(false);
      setMixKeys([]);
      go("storyboard", updated);
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to use this concept."));
    } finally {
      setPending(false);
    }
  }

  async function onBulkGenerate(options?: { seedanceModel?: string; fast?: boolean }) {
    if (!token || !project || pending || pendingFast) return;
    const preview = expandStudioBulkJobs({
      conceptIds: selectedConceptIds,
      characterIds: bulkCharacterIds,
      generateCharacter: bulkGenerateCharacter,
      genderMode: bulkGenderMode,
      durationMode: bulkDurationMode,
      durationSeconds: brief.duration || project.duration_seconds || 45,
      count: bulkCount || undefined,
    });
    if (preview.error) {
      setError(preview.error);
      return;
    }
    const fast = Boolean(options?.fast);
    const seedanceModel =
      options?.seedanceModel ||
      (fast ? "dreamina-seedance-2-0-fast-260128" : undefined);
    if (fast) setPendingFast(true);
    else setPending(true);
    setError("");
    try {
      const result = await api<{ count: number; projects: VideoProject[] }>(endpoints.ai.videoBulkGenerate(project.id), {
        method: "POST",
        token,
        body: JSON.stringify({
          concept_ids: selectedConceptIds,
          character_ids: bulkCharacterIds
            .filter((id) => characterChoices.some((item) => String(item.id) === id && characterIsVideoReady(item)))
            .map((id) => Number(id)),
          generate_character: bulkGenerateCharacter || generateCharacter,
          gender_mode: bulkGenderMode,
          duration_mode: bulkDurationMode,
          duration_seconds: brief.duration || project.duration_seconds,
          count: preview.jobs.length,
          ...(seedanceModel ? { seedance_model: seedanceModel } : {}),
        }),
      });
      const created = result.projects || [];
      created.forEach((item) => beginGenerationTimer(item.id));
      bulkModeRef.current = created.length > 1;
      setBulkProjects(created);
      setVideos((current) => [...created, ...current.filter((item) => !created.some((row) => row.id === item.id))]);
      const first = created[0];
      if (first) {
        keepProject(first);
        go("generate", first);
      }
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to start bulk generation."));
    } finally {
      if (fast) setPendingFast(false);
      else setPending(false);
    }
  }

  function toggleMixScene(conceptId: string, sceneKey: string) {
    const key = `${conceptId}:${sceneKey}`;
    setMixKeys((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  }

  function applyMix() {
    const mix = mixKeys
      .map((key) => {
        const [concept_id, scene_key] = key.split(":");
        return { concept_id, scene_key };
      })
      .filter((item) => item.concept_id && item.scene_key);
    const first = mix[0];
    if (!first) return;
    onUseConcept(first.concept_id, mix);
  }

  async function patchScene(scene: StudioScene, data: Record<string, unknown>) {
    if (!token) return;
    if (scene.approved && !data.confirm_approved_edit) {
      const ok = window.confirm("This scene is approved. Change it anyway?");
      if (!ok) return;
      data.confirm_approved_edit = true;
    }
    setPending(true);
    setError("");
    try {
      await api(endpoints.ai.videoScene(scene.id), {
        method: "PATCH",
        token,
        body: JSON.stringify(data),
      });
      const full = await api<VideoProject>(endpoints.ai.videoDetail(project!.id), { token });
      keepProject(full);
      setEditingScene(null);
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to update the scene."));
    } finally {
      setPending(false);
    }
  }

  async function changeDuration(value: number) {
    if (!token || !project) return;
    setBrief((current) => ({ ...current, duration: value }));
    setPending(true);
    setError("");
    try {
      const updated = await api<VideoProject>(endpoints.ai.videoTimeline(project.id), {
        method: "PATCH",
        token,
        body: JSON.stringify({ duration_seconds: value }),
      });
      keepProject(updated);
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to rebuild the timeline."));
    } finally {
      setPending(false);
    }
  }

  async function moveScene(scene: StudioScene, direction: -1 | 1) {
    if (!token || !project) return;
    const keys = (project.scenes || []).map((item) => item.scene_key);
    const index = keys.indexOf(scene.scene_key);
    const next = index + direction;
    if (index < 0 || next < 0 || next >= keys.length) return;
    const reordered = [...keys];
    const [removed] = reordered.splice(index, 1);
    reordered.splice(next, 0, removed);
    setPending(true);
    try {
      const updated = await api<VideoProject>(endpoints.ai.videoTimeline(project.id), {
        method: "PATCH",
        token,
        body: JSON.stringify({ scene_keys: reordered }),
      });
      keepProject(updated);
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to reorder scenes."));
    } finally {
      setPending(false);
    }
  }

  async function duplicateScene(scene: StudioScene) {
    if (!token || !project) return;
    setPending(true);
    try {
      await api(endpoints.ai.videoSceneDuplicate(scene.id), { method: "POST", token, body: JSON.stringify({}) });
      keepProject(await api<VideoProject>(endpoints.ai.videoDetail(project.id), { token }));
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to copy the scene."));
    } finally {
      setPending(false);
    }
  }

  async function deleteScene(scene: StudioScene) {
    if (!token || !project) return;
    setPending(true);
    try {
      await api(endpoints.ai.videoScene(scene.id), { method: "DELETE", token });
      keepProject(await api<VideoProject>(endpoints.ai.videoDetail(project.id), { token }));
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to delete the scene."));
    } finally {
      setPending(false);
    }
  }

  async function regenerateScene(scene: StudioScene, confirmApproved = false) {
    if (!token || !project) return;
    if (scene.approved && !confirmApproved) {
      const ok = window.confirm("This scene is approved. Regenerate it anyway?");
      if (!ok) return;
    }
    setPending(true);
    setError("");
    try {
      const updated = await api<VideoProject>(endpoints.ai.videoSceneRegenerate(scene.id), {
        method: "POST",
        token,
        body: JSON.stringify({ confirm: scene.approved || confirmApproved }),
      });
      keepProject(updated);
      setEditingScene(null);
      go("generate", updated);
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to regenerate this scene."));
    } finally {
      setPending(false);
    }
  }

  async function regenerateSceneByKey(sceneKey: string) {
    const scene = project?.scenes?.find((item) => item.scene_key === sceneKey);
    if (scene) await regenerateScene(scene);
  }

  function viewScene(sceneKey: string) {
    const scene = project?.scenes?.find((item) => item.scene_key === sceneKey);
    setSelectedSceneKey(sceneKey);
    if (scene) setEditingScene(scene);
    go("storyboard");
  }

  async function approveProject(confirm = false) {
    if (!token || !project) return;
    await runAction(
      endpoints.ai.videoApprove(project.id),
      JSON.stringify({ confirm }),
      "approve",
    );
  }

  async function approveScene(scene: StudioScene) {
    if (!token || !project) return;
    setPending(true);
    try {
      const updated = await api<VideoProject>(endpoints.ai.videoApproveScenes(project.id), {
        method: "POST",
        token,
        body: JSON.stringify({ scene_ids: [scene.id] }),
      });
      keepProject(updated);
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to approve the scene."));
    } finally {
      setPending(false);
    }
  }

  async function onGenerateProject() {
    if (!token || !project) return;
    if (!canVisitStudioStep("generate", project)) {
      setError("Choose a concept and review the storyboard before generating.");
      go("storyboard", project);
      return;
    }
    setPending(true);
    setError("");
    try {
      const saved = await saveBrief();
      if (!saved) {
        setError("Select a product before generating.");
        return;
      }
      beginGenerationTimer(saved.id);
      const updated = await api<VideoProject>(endpoints.ai.videoProjectGenerate(saved.id), {
        method: "POST",
        token,
      });
      keepProject(updated);
      go("generate", updated);
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to start generation."));
    } finally {
      setPending(false);
    }
  }

  async function onCancelGeneration() {
    const target = project || bulkProjects.find((item) => ACTIVE_STATUSES.has(item.status));
    if (!token || !target) return;
    setPending(true);
    setError("");
    try {
      const result = await api<{ project: VideoProject; stopped_ids: number[] }>(
        endpoints.ai.videoCancel(target.id),
        { method: "POST", token, body: JSON.stringify({ cancel_batch: true }) },
      );
      const stopped = new Set(result.stopped_ids || [result.project.id]);
      keepProject(result.project);
      setBulkProjects((rows) =>
        rows.map((item) => {
          if (!stopped.has(item.id)) return item;
          if (item.id === result.project.id) return result.project;
          return {
            ...item,
            status: "failed",
            error_message: result.project.error_message || "Stopped by you.",
            stage_label: result.project.stage_label || "Stopped",
          };
        }),
      );
      const refreshed = await Promise.all(
        [...stopped]
          .filter((id) => id !== result.project.id)
          .map((id) =>
            api<VideoProject>(endpoints.ai.videoDetail(id), { token }).catch(() => null),
          ),
      );
      setBulkProjects((rows) =>
        rows.map((item) => refreshed.find((row) => row?.id === item.id) || item),
      );
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to stop generation."));
    } finally {
      setPending(false);
    }
  }

  async function runAction(path: string, body?: BodyInit, next?: StudioStepId) {
    if (!token || !project) return;
    setError("");
    setPending(true);
    try {
      const updated = await api<VideoProject | { project: VideoProject }>(path, {
        method: "POST",
        token,
        body,
      });
      const nextProject =
        "project" in updated && updated.project ? updated.project : (updated as VideoProject);
      if (nextProject.id && "status" in nextProject) keepProject(nextProject);
      else keepProject(await api<VideoProject>(endpoints.ai.videoDetail(project.id), { token }));
      if (next) go(next, nextProject.id ? nextProject : project);
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to complete this step."));
    } finally {
      setPending(false);
    }
  }

  async function rerunQa() {
    if (!token || !project) return;
    setError("");
    setPending(true);
    try {
      await api(endpoints.ai.videoQa(project.id), { method: "POST", token });
      const updated = await api<VideoProject>(endpoints.ai.videoDetail(project.id), { token });
      keepProject(updated);
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to re-check this video."));
    } finally {
      setPending(false);
    }
  }

  async function applyAmendments(ids: string[], edits: Record<string, string>) {
    if (!token || !project) return;
    setPending(true);
    setError("");
    try {
      const result = await api<{ project: VideoProject }>(endpoints.ai.videoAmendments(project.id), {
        method: "POST",
        token,
        body: JSON.stringify({ recommendation_ids: ids, edits }),
      });
      keepProject(result.project);
      go("generate", result.project);
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to apply improvements."));
    } finally {
      setPending(false);
    }
  }

  const voiceChoices = voices.filter((item) => item.language === language && item.gender === gender);
  const phase = productionPhase({
    ...(project || {}),
    character_name: selectedCharacter?.name || project?.character_config?.character_name || "",
    voice_summary: selectedCharacter
      ? `${languageLabel(language)} / ${styleLabel(style)} / ${genderLabel(gender)}`
      : "",
  });
  const selectedBrand = brands.find((item) => String(item.id) === brandId) || null;
  const needsQa = Boolean(project && qaNeedsRerun(project.qa_results?.checks));
  const headerAction =
    step === "concepts"
      ? {
          label: `Generate ${Math.min(10, Math.max(1, bulkPreview.jobs.length || bulkCount || bulkPreview.combinationCount || 1))} videos`,
          onClick: () => onBulkGenerate(),
          disabled: pending || pendingFast || Boolean(bulkPreview.error) || !selectedConceptIds.length,
          pending: pending || pendingFast,
        }
      : step === "generate" && project?.status === "failed"
      ? { label: "Retry generation", onClick: () => onGenerateProject(), disabled: pending, pending }
      : generating
        ? { label: "Generating…", onClick: () => undefined, disabled: true, pending: true }
        : (step === "review" || step === "approve") && needsQa
          ? {
              label: "Run AI Review",
              onClick: () => rerunQa(),
              disabled: pending,
              pending,
              hint: "Re-checks this video only. It does not generate a new video.",
            }
          : step === "approve" && approved
            ? {
                label: "Export video",
                onClick: () => runAction(endpoints.ai.videoExport(project!.id)),
                disabled: pending,
                pending,
              }
            : null;

  return (
    <div className="studio studio-desk">
      <ProductionHeader
        phase={phase}
        productName={product?.name || "Create a product video"}
        generating={generating}
        project={project}
        action={headerAction}
      />

      <ol className="mt-4 flex gap-2 overflow-x-auto pb-1" aria-label="Studio steps">
        {STUDIO_STEPS.map((item, index) => {
          const active = item.id === step;
          const done = index < currentIndex;
          const allowed = canVisitStudioStep(item.id, project) || item.id === "compose" || done;
          return (
            <li key={item.id} className="shrink-0">
              <button
                type="button"
                onClick={() => {
                  if (allowed) go(item.id);
                }}
                aria-current={active ? "step" : undefined}
                className={`flex h-9 items-center gap-2 rounded-full border px-3 text-xs ${
                  active
                    ? "border-primary bg-[#e7fbff] text-foreground"
                    : allowed
                      ? "border-line bg-card"
                      : "border-transparent text-muted"
                }`}
              >
                <span className="font-medium">{String(index + 1).padStart(2, "0")}</span>
                {item.label}
              </button>
            </li>
          );
        })}
      </ol>

      {error ? (
        <p className="mt-4 rounded-xl border border-[#ffd0e2] bg-[#fff0f6] px-4 py-3 text-sm" role="alert">
          {error}
        </p>
      ) : null}

      <div className="mt-5 grid items-start gap-5 xl:grid-cols-[16.5rem_minmax(0,1fr)_14.5rem]">
        <BriefRail
          product={product}
          brand={selectedBrand}
          brief={brief}
          language={language}
          style={style}
          gender={gender}
          characterName={
            generateCharacter
              ? "Generate character"
              : selectedCharacter?.name || project?.character_config?.character_name || ""
          }
          onSelectProduct={() => document.getElementById("studio-product")?.focus()}
        />

        <section className="min-w-0 rounded-2xl border border-line bg-card p-4 md:p-6">
        {step === "compose" ? (
          <form onSubmit={onCreateConcepts} className="grid gap-8">
            <div>
              <h2 className="font-serif text-3xl">Product</h2>
              <p className="mt-2 text-sm text-muted">Pick a brand, category, then the product.</p>
              <div className="mt-6 grid gap-4 md:grid-cols-3">
                <label className="block text-sm">
                  Brand
                  <select
                    value={brandId}
                    onChange={(event) => selectBrand(event.target.value)}
                    className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                  >
                    <option value="">Select a brand</option>
                    {filteredBrands.map((brand) => (
                      <option key={brand.id} value={brand.id}>
                        {brand.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-sm">
                  Category
                  <select
                    value={categoryId}
                    onChange={(event) => selectCategory(event.target.value)}
                    className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                  >
                    <option value="">Select a category</option>
                    {categories.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-sm">
                  Product <span className="text-[#b71958]">*</span>
                  <select
                    id="studio-product"
                    value={productId ?? ""}
                    onChange={(event) => selectProduct(event.target.value)}
                    className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                  >
                    <option value="">Select a product</option>
                    {filteredProducts.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                        {item.price ? ` · RM ${item.price}` : ""}
                      </option>
                    ))}
                    <option value={NEW_PRODUCT}>Upload new product…</option>
                  </select>
                </label>
              </div>
              {product && productHistory.length > 0 ? (
                <label className="mt-4 block text-sm">
                  Previous versions
                  <select
                    value={historyId}
                    onChange={(event) => selectHistory(event.target.value)}
                    className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                  >
                    <option value="">Start new</option>
                    {productHistory.map((item) => (
                      <option key={item.id} value={item.id}>
                        {historyLabel(item)}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              {product ? (
                <div className="mt-5 rounded-2xl border border-line bg-background p-4">
                  <div className="flex flex-wrap items-start gap-4">
                    {product.images[0] ? (
                      <img src={product.images[0].url} alt="" className="h-20 w-20 rounded-xl object-cover" />
                    ) : null}
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">{product.name}</p>
                      <p className="mt-1 text-sm text-muted">
                        {product.brand_name}
                        {product.price ? ` · RM ${product.price}` : ""}
                        {product.offer ? ` · ${product.offer}` : ""}
                      </p>
                      {product.description ? (
                        <p className="mt-2 text-sm text-muted">{product.description}</p>
                      ) : null}
                      {product.approved_claims?.length ? (
                        <p className="mt-2 text-sm">
                          Approved claims: {product.approved_claims.join(" · ")}
                        </p>
                      ) : (
                        <p className="mt-2 text-sm text-muted">No approved claims on this product yet.</p>
                      )}
                    </div>
                  </div>
                  {product.images.length > 1 ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {product.images.slice(1, 5).map((image) => (
                        <img key={image.id} src={image.url} alt="" className="h-12 w-12 rounded-lg object-cover" />
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>

            <div className="border-t border-line pt-8">
              <p className="text-xs uppercase tracking-[0.18em] text-gold">Step 1</p>
              <h2 className="mt-2 font-serif text-3xl">Tell us about your video</h2>
              <p className="mt-2 text-sm text-muted">
                No prompt writing. Answer these in ordinary business language.
              </p>
              <div className="mt-6">
                <CreativeBriefWizard brief={brief} onChange={setBrief} />
              </div>
            </div>

            <div className="rounded-2xl border border-line bg-background p-5">
              <h3 className="font-medium">Speaker</h3>
              <p className="mt-1 text-sm text-muted">Tone, gender, and locale for the voice.</p>
              <div className="mt-5 grid gap-4 md:grid-cols-3">
                <label className="block text-sm">
                  Tone
                  <select
                    value={style}
                    onChange={(event) => setStyle(event.target.value)}
                    className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
                  >
                    {STYLE_OPTIONS.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-sm">
                  Gender
                  <select
                    value={gender}
                    onChange={(event) => {
                      setGender(event.target.value);
                      setVoiceId("");
                    }}
                    className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
                  >
                    {GENDER_OPTIONS.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <label className="block text-sm">
                  Locale
                  <span className="mt-0.5 block text-xs text-muted">Chinese, Cantonese, and Hokkien are separate spoken languages.</span>
                  <select
                    value={language}
                    onChange={(event) => {
                      setLanguage(event.target.value);
                      setVoiceId("");
                    }}
                    className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
                  >
                    {LANGUAGE_OPTIONS.map((option) => (
                      <option key={option.id} value={option.id} title={option.hint}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-sm">
                  Preferred voice
                  <select
                    value={voiceChoices.some((item) => item.voice_id === voiceId) ? voiceId : voiceChoices[0]?.voice_id || ""}
                    onChange={(event) => setVoiceId(event.target.value)}
                    className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
                  >
                    {voiceChoices.map((option) => (
                      <option key={option.voice_id} value={option.voice_id}>
                        {option.voice_name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </div>

            <div className="rounded-2xl border border-line bg-background p-5">
              <h3 className="font-medium">Character <span className="text-[#b71958]">*</span></h3>
              <p className="mt-1 text-sm text-muted">
                Required. Choose a character from the list, or check Generate character.
              </p>
              <label className="mt-4 block text-sm">
                Character
                <select
                  required={!generateCharacter}
                  value={generateCharacter ? "" : characterId}
                  disabled={generateCharacter}
                  onChange={(event) => {
                    const next = characters.find((item) => String(item.id) === event.target.value) || null;
                    chooseCharacter(next);
                  }}
                  className="mt-2 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold disabled:opacity-60"
                >
                  <option value="">Select a character</option>
                  {characterChoices.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                      {item.brand_name ? ` · ${item.brand_name}` : ""}
                      {characterIsVideoReady(item) ? "" : " (master required)"}
                    </option>
                  ))}
                </select>
              </label>
              {!characterChoices.length ? (
                <p className="mt-2 text-sm text-muted">
                  No saved characters yet. Check Generate character to continue.
                </p>
              ) : null}
              <label className="mt-4 flex items-start gap-3 text-sm">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4"
                  checked={generateCharacter}
                  onChange={(event) => {
                    const checked = event.target.checked;
                    setGenerateCharacter(checked);
                    if (checked) {
                      chooseCharacter(null);
                      setCharacterNote("We'll generate a character for this video.");
                    } else {
                      setCharacterNote("");
                    }
                  }}
                />
                <span>
                  <span className="font-medium">Generate character</span>
                  <span className="mt-0.5 block text-muted">
                    Create a new on-camera person for this video instead of using a saved character.
                  </span>
                </span>
              </label>
              {characterNote ? <p className="mt-2 text-sm text-muted">{characterNote}</p> : null}
              {selectedCharacter && !generateCharacter && !characterIsVideoReady(selectedCharacter) ? (
                <p className="mt-2 text-sm text-[#b71958]" role="alert">
                  {MASTER_REQUIRED_MESSAGE}
                </p>
              ) : null}
            </div>

            <div className="flex flex-wrap items-end justify-between gap-3 border-t border-line pt-8">
              <div className="min-w-0 flex-1">
                <p className="text-sm text-muted">
                  {draftNote
                    ? draftNote
                    : product
                      ? `${product.name} · ${styleLabel(style)} · ${genderLabel(gender)} · ${languageLabel(language)}`
                      : "Select a product to continue."}
                </p>
                {conceptGaps.length ? (
                  <div
                    className="mt-3 rounded-xl border border-[#ffd0e2] bg-[#fff0f6] px-4 py-3 text-sm"
                    role="status"
                  >
                    <p className="font-medium">Complete these before creating concepts:</p>
                    <ul className="mt-2 grid gap-1">
                      {conceptChecks.map((item) => (
                        <li key={item.id} className={item.ready ? "text-muted" : "text-foreground"}>
                          {item.ready ? "✓" : "○"} {item.label}
                          {item.ready ? "" : ` — ${item.hint}`}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-3">
                <SecondaryButton type="button" disabled={pending || savingDraft || !product} onClick={onSaveDraft}>
                  {savingDraft ? "Saving…" : "Save as draft"}
                </SecondaryButton>
                <PrimaryButton type="submit" disabled={pending || savingDraft || !canCreateConcepts}>
                  {pending ? "Creating ideas…" : "Create 3 concepts"}
                </PrimaryButton>
              </div>
            </div>
          </form>
        ) : null}

        {step === "concepts" ? (
          <ConceptCards
            concepts={concepts}
            selectedId={project?.selected_concept_id}
            selectedConceptIds={selectedConceptIds}
            mixing={mixing}
            pending={pending}
            duration={brief.duration || project?.duration_seconds}
            durationMode={bulkDurationMode}
            genderMode={bulkGenderMode}
            videoCount={Math.min(10, Math.max(1, bulkPreview.jobs.length || bulkCount || bulkPreview.combinationCount || 1))}
            combinationCount={bulkPreview.combinationCount}
            bulkError={bulkPreview.error}
            characters={characterChoices}
            selectedCharacterIds={bulkCharacterIds}
            generateCharacter={bulkGenerateCharacter}
            onToggleConcept={(id) =>
              setSelectedConceptIds((current) =>
                current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
              )
            }
            onSelectAllConcepts={setSelectedConceptIds}
            onDuration={changeDuration}
            onDurationMode={setBulkDurationMode}
            onGenderMode={setBulkGenderMode}
            onVideoCount={setBulkCount}
            onToggleCharacter={(id) =>
              setBulkCharacterIds((current) =>
                current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
              )
            }
            onGenerateCharacter={setBulkGenerateCharacter}
            onEdit={(id) => onUseConcept(id)}
            onMix={() => setMixing((open) => !open)}
            onToggleMixScene={toggleMixScene}
            mixKeys={mixKeys}
            onApplyMix={applyMix}
            onRegenerate={() =>
              onCreateConcepts(
                undefined,
                Math.min(10, Math.max(1, bulkCount || bulkPreview.combinationCount || 3)),
              )
            }
            onBulkGenerate={() => onBulkGenerate()}
            onBulkGenerateFast={() => onBulkGenerate({ fast: true })}
            pendingFast={pendingFast}
          />
        ) : null}

        {step === "storyboard" && project ? (
          <StoryboardTimeline
            scenes={project.scenes || []}
            duration={brief.duration || project.duration_seconds}
            pending={pending}
            selectedKey={selectedSceneKey}
            onSelect={(scene) => setSelectedSceneKey(scene.scene_key)}
            onDuration={changeDuration}
            onEdit={setEditingScene}
            onDuplicate={duplicateScene}
            onDelete={deleteScene}
            onMove={moveScene}
            onLock={(scene, key, value) => patchScene(scene, { [key]: value })}
            onRegenerate={(scene) => regenerateScene(scene)}
            onApprove={approveScene}
            onGenerate={onGenerateProject}
            characterName={selectedCharacter?.name || project?.character_config?.character_name || ""}
          />
        ) : null}

        {step === "generate" ? (
          bulkProjects.length > 1 ? (
            <BulkGenerationProgress
              projects={bulkProjects}
              selectedId={project?.id}
              pending={pending}
              onSelect={(item) => keepProject(item)}
              onRetry={onGenerateProject}
              onCancel={onCancelGeneration}
              onBack={() => {
                const sourceId = Number((project?.creative_brief || {}).bulk_source_project_id || 0);
                const source = videos.find((item) => item.id === sourceId);
                bulkModeRef.current = false;
                if (source) keepProject(source);
                go("concepts", source || project);
              }}
            />
          ) : project && (generating || project.status === "failed") ? (
            <GenerationProgress
              project={project}
              pending={pending}
              onRetry={onGenerateProject}
              onCancel={onCancelGeneration}
              onBack={() => go(project.selected_concept_id ? "storyboard" : "concepts")}
              onEditFailed={() => go(project.selected_concept_id ? "storyboard" : "concepts")}
            />
          ) : (
            <div className="mx-auto max-w-xl">
              <h2 className="font-serif text-3xl">Ready to generate</h2>
              <p className="mt-2 text-sm text-muted">
                The storyboard is the source of truth. Generated output is 9:16.
              </p>
              <div className="mt-6 flex flex-wrap gap-3">
                <PrimaryButton
                  type="button"
                  disabled={pending || !project || !canVisitStudioStep("generate", project)}
                  onClick={onGenerateProject}
                >
                  {pending ? "Starting…" : "Generate video"}
                </PrimaryButton>
                <SecondaryButton type="button" onClick={() => go(project?.selected_concept_id ? "storyboard" : "concepts")}>
                  Back to {project?.selected_concept_id ? "storyboard" : "concepts"}
                </SecondaryButton>
              </div>
            </div>
          )
        ) : null}

        {step === "review" && project ? (
          <VideoReview
            project={project}
            pending={pending}
            showCorrection={showCorrection}
            correction={correction}
            onCorrection={setCorrection}
            onCorrectionVoice={setCorrectionVoice}
            onApplyCorrection={() => {
              const payload = new FormData();
              payload.append("instruction", correction);
              if (correctionVoice) payload.append("voice", correctionVoice);
              runAction(endpoints.ai.videoCorrect(project.id), payload, "generate");
            }}
            onToggleCorrection={() => setShowCorrection((open) => !open)}
            onApprove={(confirm) => approveProject(Boolean(confirm))}
            onNew={resetCompose}
            onApplyAmendments={applyAmendments}
            onViewScene={viewScene}
            onRegenerateScene={regenerateSceneByKey}
            onRerunQa={rerunQa}
            onSelectScene={setSelectedSceneKey}
            selectedSceneKey={selectedSceneKey}
          />
        ) : null}

        {step === "approve" && project ? (
          <ApprovalControls
            project={project}
            approved={approved}
            pending={pending}
            credits={credits}
            publishPlatform={publishPlatform}
            publishAuthorized={publishAuthorized}
            publishNote={publishNote}
            onApprove={(confirm) => approveProject(Boolean(confirm))}
            onExport={() => runAction(endpoints.ai.videoExport(project.id))}
            onNew={resetCompose}
            onPlatform={setPublishPlatform}
            onAuthorized={setPublishAuthorized}
            onPublish={() => {
              const payload = new FormData();
              payload.append("platform", publishPlatform);
              payload.append("authorized", "true");
              setPublishNote("");
              runAction(endpoints.ai.videoPublish(project.id), payload).then(() => {
                setPublishNote("Saved. Nothing was posted yet.");
              });
            }}
            onRerunQa={rerunQa}
          />
        ) : null}

        {!generating && step !== "compose" ? (
          <div className="mt-8 flex flex-wrap justify-between gap-3">
            <SecondaryButton type="button" onClick={() => go(previousStep(step))}>
              Back
            </SecondaryButton>
          </div>
        ) : null}
      </section>

        <DirectorNotes phase={phase} generating={generating} />
      </div>

      {editingScene ? (
        <SceneEditor
          scene={editingScene}
          pending={pending}
          onSave={(patch) => patchScene(editingScene, patch)}
          onCancel={() => setEditingScene(null)}
          onRegenerate={(confirm) => regenerateScene(editingScene, confirm)}
        />
      ) : null}

      {showProductModal ? (
        <StudioProductModal
          token={token}
          brands={brands}
          defaultBrand={brandId || String(brands[0]?.id || "")}
          onClose={() => setShowProductModal(false)}
          onSaved={(created) => {
            setProducts((current) => [created, ...current]);
            setBrandId(String(created.brand));
            setCategoryId(String(created.category));
            setProductId(created.id);
            setBrief((current) => ({
              ...current,
              original_price: created.price || current.original_price,
              offer_text: created.offer || current.offer_text,
            }));
            setShowProductModal(false);
          }}
        />
      ) : null}
    </div>
  );
}

function mergeSceneStatus(
  scenes: StudioScene[] = [],
  live?: VideoStatus["scene_statuses"],
): StudioScene[] {
  if (!live?.length) return scenes;
  return scenes.map((scene) => {
    const match = live.find((item) => item.scene_key === scene.scene_key || item.id === scene.id);
    if (!match) return scene;
    return { ...scene, scene_status: match.status, error: match.error };
  });
}
