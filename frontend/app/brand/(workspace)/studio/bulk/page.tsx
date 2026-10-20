"use client";

import { useEffect, useMemo, useState } from "react";

import { BulkConfigure } from "@/components/studio/bulk/BulkConfigure";
import { BulkModePicker } from "@/components/studio/bulk/BulkModePicker";
import { BulkPlanEditor } from "@/components/studio/bulk/BulkPlanEditor";
import { BulkProgress } from "@/components/studio/bulk/BulkProgress";
import { PrimaryButton } from "@/components/studio/ui";
import {
  api,
  endpoints,
  type BulkGeneration,
  type BulkStudioMode,
  type BulkVariation,
  type Product,
  type StudioCharacter,
  type VideoProject,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  BULK_STUDIO_STEPS,
  acceptedReferenceVideo,
  bulkStepForStatus,
  canGeneratePlan,
  canUseLibraryVideoForBulk,
  isBulkBusy,
  isReferenceMode,
  isSameFlowMode,
  planRows,
  type BulkStudioStepId,
} from "@/lib/bulk-studio";
import { beginGenerationTimer, libraryVideoSrc, merchantError } from "@/lib/studio";

const emptyLocks = {
  character: false,
  product: true,
  brand: true,
  price: true,
  cta: true,
};
const emptyVariables = {
  story: true,
  location: true,
  hook: true,
  action: true,
  camera: true,
};

export default function BulkStudioPage() {
  const { token } = useAuth();
  const [step, setStep] = useState<BulkStudioStepId>("mode");
  const [mode, setMode] = useState<BulkStudioMode | "">("");
  const [products, setProducts] = useState<Product[]>([]);
  const [characters, setCharacters] = useState<StudioCharacter[]>([]);
  const [productId, setProductId] = useState<number | "">("");
  const [characterId, setCharacterId] = useState<number | "">("");
  const [characterIds, setCharacterIds] = useState<number[]>([]);
  const [language, setLanguage] = useState("conversational_bm");
  const [speakingStyle, setSpeakingStyle] = useState("warm");
  const [duration, setDuration] = useState(30);
  const [count, setCount] = useState(10);
  const [locks, setLocks] = useState<Record<string, boolean>>(emptyLocks);
  const [variables, setVariables] = useState<Record<string, boolean>>(emptyVariables);
  const [instruction, setInstruction] = useState("");
  const [videos, setVideos] = useState<VideoProject[]>([]);
  const [reference, setReference] = useState<File | null>(null);
  const [referencePreview, setReferencePreview] = useState("");
  const [sourceVideo, setSourceVideo] = useState<VideoProject | null>(null);
  const [batch, setBatch] = useState<BulkGeneration | null>(null);
  const [plan, setPlan] = useState<BulkVariation[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    Promise.all([
      api<Product[]>(endpoints.brands.products, { token }).catch(() => []),
      api<StudioCharacter[]>(endpoints.ai.characters, { token }).catch(() => []),
      api<VideoProject[]>(endpoints.ai.videos, { token }).catch(() => []),
    ]).then(([nextProducts, nextCharacters, nextVideos]) => {
      setProducts(nextProducts);
      setCharacters(nextCharacters);
      setVideos(nextVideos);
    });
    const sourceId = Number(new URLSearchParams(window.location.search).get("source") || "");
    if (!sourceId) return;
    api<VideoProject>(endpoints.ai.videoDetail(sourceId), { token })
      .then((project) => {
        if (!canUseLibraryVideoForBulk(project)) {
          setError("That video is not ready to use as a Bulk Studio reference yet.");
          return;
        }
        setSourceVideo(project);
        setProductId(project.product);
        if (project.character_config?.character) setCharacterId(project.character_config.character);
        setLanguage(project.language);
        setSpeakingStyle(project.speaking_style);
        if (project.duration_seconds) setDuration(project.duration_seconds);
        const sourceInstruction = String((project.creative_brief || {}).legacy_instructions || "").trim();
        if (sourceInstruction) setInstruction(sourceInstruction);
        applyMode("existing_video");
        setStep("configure");
      })
      .catch(() => setError("Unable to load that library video as a reference."));
  }, [token]);

  useEffect(() => {
    return () => {
      if (referencePreview) URL.revokeObjectURL(referencePreview);
    };
  }, [referencePreview]);

  useEffect(() => {
    if (!token || !batch || !isBulkBusy(batch.status)) return;
    const timer = window.setInterval(() => {
      api<BulkGeneration>(endpoints.ai.bulkVideoStatus(batch.id), { token })
        .then((next) => setBatch(next))
        .catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [token, batch?.id, batch?.status]);

  const analyzed = Boolean(batch?.master_spec && Object.keys(batch.master_spec).length);
  const currentIndex = BULK_STUDIO_STEPS.findIndex((item) => item.id === step);

  const header = useMemo(() => {
    if (step === "mode") return { title: "Bulk Studio", note: "Create multiple videos from one base creative." };
    if (step === "configure") return { title: "Configure the batch", note: "Choose what stays the same and what can change." };
    if (step === "plan") return { title: "Approve the variation plan", note: "Edit, remove, or regenerate items before generation starts." };
    return { title: batch?.title || "Generating videos", note: "Each video is a normal Studio project." };
  }, [step, batch?.title]);

  function applyMode(next: BulkStudioMode) {
    setMode(next);
    if (next === "character") {
      setLocks({ character: true, product: true, brand: true, voice: true, price: true, cta: true });
      setVariables({ story: true, location: true, action: true, camera: true, hook: true, environment: true });
    } else if (next === "product") {
      setLocks({ product: true, product_appearance: true, price: true, cta: true, brand: true, offer: true });
      setVariables({ story: true, hook: true, location: true, action: true, camera: true, environment: true });
    } else if (next === "existing_video") {
      setLocks({
        story: true,
        scenes: true,
        script: true,
        dialogue: true,
        timing: true,
        cta: true,
        product: true,
        duration: true,
      });
      setVariables({ location: true, character: false, product: false, story: false });
    } else if (next === "reference_location") {
      setLocks({
        story: true,
        scenes: true,
        character: true,
        dialogue: true,
        timing: true,
        camera: true,
        product: true,
        cta: true,
      });
      setVariables({ location: true, environment: true });
    } else {
      setLocks({
        story: true,
        scenes: true,
        dialogue: true,
        timing: true,
        camera: true,
        location: true,
        product: true,
        cta: true,
      });
      setVariables({ character: true });
    }
  }

  async function saveDraft() {
    if (!token || !mode || !productId) throw new Error("Select a product.");
    const body = new FormData();
    body.set("mode", mode);
    body.set("product_id", String(productId));
    body.set("requested_count", String(mode === "reference_character" ? characterIds.length || count : count));
    body.set("language", language);
    body.set("speaking_style", speakingStyle);
    body.set("duration_seconds", String(duration));
    body.set("locks", JSON.stringify(locks));
    body.set("variables", JSON.stringify(variables));
    const resolvedCharacter = characterId || sourceVideo?.character_config?.character;
    if (resolvedCharacter) body.set("character_id", String(resolvedCharacter));
    characterIds.forEach((id) => body.append("character_ids", String(id)));
    if (instruction.trim()) body.set("instruction", instruction.trim());
    if (reference) body.set("reference_video", reference);
    else if (sourceVideo?.id) body.set("source_video_id", String(sourceVideo.id));
    const saved = await api<BulkGeneration>(endpoints.ai.bulkVideos, { token, method: "POST", body });
    setBatch(saved);
    return saved;
  }

  async function createPlan() {
    if (!token || !mode) return;
    if (
      !canGeneratePlan({
        mode,
        productId,
        characterId,
        characterIds,
        hasReference:
          Boolean(reference) ||
          Boolean(batch?.reference_video_url) ||
          canUseLibraryVideoForBulk(sourceVideo),
      })
    ) {
      setError("Fill the required base asset before planning videos.");
      return;
    }
    setPending(true);
    setError("");
    try {
      const current = batch && batch.mode === mode ? batch : await saveDraft();
      if (isReferenceMode(mode) && !current.master_spec?.scenes) {
        const analyzedBatch = await api<BulkGeneration>(endpoints.ai.bulkVideoAnalyze(current.id), {
          token,
          method: "POST",
          body: JSON.stringify({ instruction }),
        });
        setBatch(analyzedBatch);
      }
      const planned = await api<BulkGeneration>(endpoints.ai.bulkVideoPlan(current.id), {
        token,
        method: "POST",
        body: JSON.stringify({ instruction }),
      });
      setBatch(planned);
      setPlan(planRows(planned));
      setStep("plan");
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to generate the plan."));
    } finally {
      setPending(false);
    }
  }

  async function analyzeReference() {
    if (!token) return;
    setPending(true);
    setError("");
    try {
      const current = batch || (await saveDraft());
      const next = await api<BulkGeneration>(endpoints.ai.bulkVideoAnalyze(current.id), {
        token,
        method: "POST",
        body: JSON.stringify({ instruction }),
      });
      setBatch(next);
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to analyze the reference video."));
    } finally {
      setPending(false);
    }
  }

  async function persistPlan(nextPlan: BulkVariation[]) {
    if (!token || !batch) return;
    const saved = await api<BulkGeneration>(endpoints.ai.bulkVideoPatchPlan(batch.id), {
      token,
      method: "PATCH",
      body: JSON.stringify({ variations: nextPlan, instruction }),
    });
    setBatch(saved);
    setPlan(planRows(saved));
  }

  async function generateVideos() {
    if (!token || !batch) return;
    setPending(true);
    setError("");
    try {
      await persistPlan(plan);
      const next = await api<BulkGeneration>(endpoints.ai.bulkVideoGenerate(batch.id), {
        token,
        method: "POST",
        body: JSON.stringify({ instruction }),
      });
      setBatch(next);
      beginGenerationTimer(`bulk-${next.id}`);
      next.items.forEach((item) => {
        if (item.video_project?.id) beginGenerationTimer(item.video_project.id);
      });
      setStep("generate");
    } catch (err) {
      setError(merchantError(err instanceof Error ? err.message : "Unable to start bulk generation."));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="studio studio-desk">
      <header className="rounded-2xl border border-line bg-card px-4 py-4 md:px-5">
        <p className="text-[11px] font-extrabold uppercase tracking-[0.16em] text-primary">Bulk Studio</p>
        <h1 className="mt-1 font-serif text-2xl md:text-3xl">{header.title}</h1>
        <p className="mt-2 text-sm text-muted">{header.note}</p>
      </header>

      <ol className="mt-4 flex gap-2 overflow-x-auto pb-1" aria-label="Bulk Studio steps">
        {BULK_STUDIO_STEPS.map((item, index) => {
          const active = item.id === step;
          const allowed = index <= currentIndex || (batch && bulkStepForStatus(batch.status) === item.id);
          return (
            <li key={item.id}>
              <button
                type="button"
                className={`flex h-9 items-center gap-2 rounded-full border px-3 text-xs ${
                  active ? "border-primary bg-[#e7fbff]" : "border-line bg-card"
                }`}
                onClick={() => allowed && setStep(item.id)}
              >
                <span className="font-medium">{String(index + 1).padStart(2, "0")}</span>
                {item.label}
              </button>
            </li>
          );
        })}
      </ol>

      {error ? <p className="mt-4 text-sm text-[#b71958]">{error}</p> : null}

      <div className="mt-6">
        {step === "mode" ? (
          <div className="grid gap-5">
            <BulkModePicker
              selected={mode}
              onSelect={(next) => {
                applyMode(next);
              }}
            />
            <PrimaryButton type="button" disabled={!mode} onClick={() => setStep("configure")}>
              Continue
            </PrimaryButton>
          </div>
        ) : null}

        {step === "configure" && mode ? (
          <>
          {sourceVideo ? (
            <p className="mb-4 rounded-2xl border border-line bg-card px-4 py-3 text-sm">
              Using {sourceVideo.product_name || `video ${sourceVideo.id}`} as the{" "}
              {isSameFlowMode(mode) ? "master video flow" : "reference"}. You can still change the mode or pick a different video.
            </p>
          ) : null}
          <BulkConfigure
            mode={mode}
            products={products}
            characters={characters}
            videos={videos}
            sourceVideoId={sourceVideo?.id || ""}
            analysis={batch?.master_spec?.analysis as Record<string, unknown> | undefined}
            productId={productId}
            characterId={characterId}
            characterIds={characterIds}
            language={language}
            speakingStyle={speakingStyle}
            duration={duration}
            count={count}
            locks={locks}
            variables={variables}
            referenceName={
              reference?.name ||
              batch?.reference_video_url ||
              (sourceVideo ? sourceVideo.product_name || `Library video ${sourceVideo.id}` : "")
            }
            referenceUrl={referencePreview || batch?.reference_video_url || (sourceVideo ? libraryVideoSrc(sourceVideo) : "")}
            analyzed={analyzed}
            pending={pending}
            onProduct={setProductId}
            onCharacter={setCharacterId}
            onCharacters={setCharacterIds}
            onLanguage={setLanguage}
            onStyle={setSpeakingStyle}
            onDuration={setDuration}
            onCount={setCount}
            instruction={instruction}
            onInstruction={setInstruction}
            onSourceVideo={(id) => {
              const next = videos.find((item) => item.id === id) || null;
              setSourceVideo(next);
              if (next) {
                setProductId(next.product);
                if (next.character_config?.character) setCharacterId(next.character_config.character);
                if (next.duration_seconds) setDuration(next.duration_seconds);
                setLanguage(next.language);
                setSpeakingStyle(next.speaking_style);
              }
            }}
            onToggleVariable={(key) => setVariables((current) => ({ ...current, [key]: !current[key] }))}
            onReference={(file) => {
              if (file && !acceptedReferenceVideo(file)) {
                setError("Upload an MP4, MOV, or WebM reference video.");
                return;
              }
              setError("");
              setReference(file);
              setReferencePreview(file ? URL.createObjectURL(file) : "");
            }}
            onAnalyze={analyzeReference}
            onBack={() => setStep("mode")}
            onContinue={createPlan}
          />
          </>
        ) : null}

        {step === "plan" ? (
          <BulkPlanEditor
            rows={plan}
            pending={pending}
            instruction={instruction}
            onInstruction={setInstruction}
            onChange={(index, patch) => setPlan((current) => current.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)))}
            onRemove={(index) => setPlan((current) => current.filter((_, rowIndex) => rowIndex !== index))}
            onMove={(index, direction) =>
              setPlan((current) => {
                const next = [...current];
                const swap = index + direction;
                if (!next[swap]) return current;
                [next[index], next[swap]] = [next[swap], next[index]];
                return next;
              })
            }
            onRegenerateItem={async (sequence) => {
              if (!token || !batch) return;
              setPending(true);
              try {
                const next = await api<BulkGeneration>(endpoints.ai.bulkVideoPatchPlan(batch.id), {
                  token,
                  method: "PATCH",
                  body: JSON.stringify({ regenerate_sequence: sequence, instruction }),
                });
                setBatch(next);
                setPlan(planRows(next));
              } catch (err) {
                setError(merchantError(err instanceof Error ? err.message : "Unable to regenerate that item."));
              } finally {
                setPending(false);
              }
            }}
            onRegenerateAll={createPlan}
            onBack={() => setStep("configure")}
            onGenerate={generateVideos}
          />
        ) : null}

        {step === "generate" && batch ? (
          <BulkProgress
            batch={batch}
            pending={pending}
            onRetry={async () => {
              if (!token) return;
              setPending(true);
              try {
                setBatch(await api<BulkGeneration>(endpoints.ai.bulkVideoRetry(batch.id), { token, method: "POST", body: "{}" }));
              } catch (err) {
                setError(merchantError(err instanceof Error ? err.message : "Unable to retry failed videos."));
              } finally {
                setPending(false);
              }
            }}
            onCancel={async () => {
              if (!token) return;
              setPending(true);
              try {
                setBatch(
                  await api<BulkGeneration>(endpoints.ai.bulkVideoCancel(batch.id), {
                    token,
                    method: "POST",
                    body: "{}",
                  }),
                );
              } catch (err) {
                setError(merchantError(err instanceof Error ? err.message : "Unable to stop this batch."));
              } finally {
                setPending(false);
              }
            }}
            onBack={() => {
              setBatch(null);
              setPlan([]);
              setStep("mode");
            }}
          />
        ) : null}
      </div>
    </div>
  );
}
