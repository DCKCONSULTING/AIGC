"use client";

import { useState } from "react";
import Link from "next/link";

import type { VideoProject } from "@/lib/api";
import { amendmentsFrom, formatClock } from "@/lib/director";
import {
  approvalBlockSummary,
  confidenceLabel,
  identityPassed,
  identityScoreLabel,
  merchantQaDetail,
  narrationPassed,
  pipelineStageLabel,
  qaCardDetail,
  qaIncomplete,
  qaIssueCards,
  qaLayerSummary,
  qaNeedsRerun,
  qaStatusLabel,
  releaseBlockingIssues,
  sceneGateFailures,
  seriousQaIssues,
} from "@/lib/studio";
import { AmendmentAssistant } from "./AmendmentAssistant";
import { GenerationTimer } from "./GenerationTimer";
import { VideoStage } from "./VideoStage";
import { PrimaryButton, SecondaryButton, StatusMark } from "./ui";

export function VideoReview({
  project,
  pending,
  showCorrection,
  correction,
  onCorrection,
  onCorrectionVoice,
  onApplyCorrection,
  onToggleCorrection,
  onApprove,
  onNew,
  onApplyAmendments,
  onViewScene,
  onRegenerateScene,
  onRerunQa,
}: {
  project: VideoProject;
  pending: boolean;
  showCorrection: boolean;
  correction: string;
  onCorrection: (value: string) => void;
  onCorrectionVoice: (file: File | null) => void;
  onApplyCorrection: () => void;
  onToggleCorrection: () => void;
  onApprove: (confirm?: boolean) => void;
  onNew: () => void;
  onApplyAmendments: (ids: string[], edits: Record<string, string>) => void;
  onViewScene?: (sceneKey: string) => void;
  onRegenerateScene?: (sceneKey: string) => void;
  onRerunQa?: () => void;
  onSelectScene?: (sceneKey: string) => void;
  selectedSceneKey?: string | null;
}) {
  const checks = project.qa_results?.checks;
  const gates = project.qa_results?.scene_gates || [];
  const failedGates = sceneGateFailures(gates);
  const gateSummary = approvalBlockSummary(gates);
  const layers = qaLayerSummary(project.qa_results?.layers, project.qa_results?.checks);
  const qaStatus = project.qa_status || "";
  const issues = qaIssueCards(checks);
  const serious = seriousQaIssues(checks);
  const blocking = project.qa_results?.release_blocking?.length
    ? project.qa_results.release_blocking
    : releaseBlockingIssues(checks, { hasPreview: Boolean(project.preview_url) });
  const needsRerun = qaNeedsRerun(checks);
  const incomplete = qaIncomplete(checks);
  const [ignored, setIgnored] = useState(false);
  const [selectedIssues, setSelectedIssues] = useState<string[]>([]);
  const [confirmSerious, setConfirmSerious] = useState(false);
  const recommendations = ignored ? [] : amendmentsFrom(project);
  const uncheckedBlockers = blocking.filter(
    (item) => item.status === "not_checked" || item.status === "skipped",
  );

  function issueKey(issue: (typeof issues)[number], index: number) {
    return `${issue.name}-${issue.scene_id || ""}-${index}`;
  }

  function toggleIssue(key: string) {
    setSelectedIssues((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  }

  return (
    <div className="grid gap-8">
      <div className="grid gap-8 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
        <VideoStage project={project} />
        <div>
          <h2 className="font-serif text-3xl text-foreground">Review video</h2>
          <GenerationTimer project={project} running={false} className="mt-3" size="sm" />
          <p className="mt-2 text-sm font-medium">
            {blocking.length || failedGates.length
              ? gateSummary || "Approval blocked"
              : qaStatus === "failed"
                ? "Needs a fix"
                : qaStatus === "warning"
                  ? "Review recommended"
                  : qaStatus === "passed"
                    ? "QA passed"
                    : "Ready for review"}
          </p>
          <ul className="mt-5 grid gap-2 sm:grid-cols-2">
            {layers.map((item) => (
              <li key={item.key} className="flex items-start gap-3 rounded-xl border border-line px-3 py-2.5 text-sm">
                <StatusMark status={item.mark} />
                <div>
                  <p>
                    {item.label}: {qaStatusLabel(item.mark)}
                  </p>
                  <p className="mt-1 text-xs text-muted">{qaCardDetail(item)}</p>
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-muted">
            NOT CHECKED is not a pass. A check is only marked passed after it actually runs.
          </p>

          {blocking.length ? (
            <div className="mt-5 rounded-xl border border-[#ffd0e2] bg-[#fff0f6] p-4 text-sm">
              <p className="font-medium">Approval blocked</p>
              {blocking.map((item, index) => (
                <p key={`${item.name}-${index}`} className="mt-2">
                  <span className="font-medium">
                    {item.name === "product_visual_consistency"
                      ? "Product visual verification"
                      : (item.name || "").includes("audio") || item.name === "assembled_audio"
                        ? "Audio output"
                        : item.name === "ai_review"
                          ? "Language review"
                          : item.name}{" "}
                    {qaStatusLabel(item.status || "not_checked")}
                  </span>
                  {": "}
                  {item.detail}
                </p>
              ))}
              <p className="mt-2 text-muted">
                {uncheckedBlockers.length
                  ? "Required AI visual verification has not completed."
                  : "Approval is blocked until these failures are fixed."}
              </p>
            </div>
          ) : null}

          {needsRerun && onRerunQa ? (
            <div className="mt-5">
              <PrimaryButton type="button" disabled={pending} onClick={onRerunQa}>
                {pending ? "AI review in progress…" : "Run AI Review"}
              </PrimaryButton>
              <p className="mt-2 text-xs text-muted">
                Re-checks this video only. It does not generate a new video.
              </p>
            </div>
          ) : null}

          {issues.length ? (
            <div className="mt-6 grid gap-3">
              <h3 className="font-medium">QA issues</h3>
              {issues.map((issue, index) => {
                const key = issueKey(issue, index);
                const selected = selectedIssues.includes(key);
                const sceneKey = issue.scene_id || issue.affected_scenes?.[0] || "";
                return (
                  <article key={key} className="rounded-xl border border-line p-4">
                    <p className="text-xs uppercase tracking-[0.16em] text-primary">
                      {confidenceLabel(issue)}
                      {issue.start != null || issue.end != null
                        ? ` · ${formatClock(issue.start)}–${formatClock(issue.end)}`
                        : ""}
                    </p>
                    <p className="mt-2 font-medium">{merchantQaDetail(issue.detail)}</p>
                    {issue.reason || issue.stage ? (
                      <p className="mt-1 text-sm">
                        {issue.reason ? `Reason: ${merchantQaDetail(issue.reason)}` : null}
                        {issue.stage ? ` Stage: ${pipelineStageLabel(issue.stage)}.` : ""}
                      </p>
                    ) : null}
                    <p className="mt-1 text-sm text-muted">
                      {issue.source === "multimodal" || issue.source === "transcription" || issue.source === "OCR"
                        ? "AI detected a possible issue. This is not a definite failure."
                        : issue.recommended_action || ""}
                    </p>
                    {issue.frame_url ? (
                      <img src={issue.frame_url} alt="QA frame" className="mt-3 h-28 w-20 rounded-xl object-cover" />
                    ) : null}
                    <div className="mt-3 flex flex-wrap gap-2">
                      <SecondaryButton type="button" onClick={() => toggleIssue(key)}>
                        {selected ? "Selected" : "Select"}
                      </SecondaryButton>
                      {sceneKey && onViewScene ? (
                        <SecondaryButton type="button" onClick={() => onViewScene(sceneKey)}>
                          View scene
                        </SecondaryButton>
                      ) : null}
                      {sceneKey && onRegenerateScene ? (
                        <SecondaryButton type="button" onClick={() => onRegenerateScene(sceneKey)}>
                          Regenerate scene
                        </SecondaryButton>
                      ) : null}
                    </div>
                  </article>
                );
              })}
            </div>
          ) : null}

          <AmendmentAssistant
            recommendations={recommendations}
            pending={pending}
            qaIncomplete={incomplete}
            onApply={onApplyAmendments}
            onIgnore={() => setIgnored(true)}
          />

          <div className="mt-6 rounded-xl border border-line bg-[#f7faff] p-4">
            <h3 className="font-medium">Ask MISA for a change</h3>
            <p className="mt-1 text-sm text-muted">
              Natural-language revision. Example: “Make the opening more festive.” This regenerates only the affected part.
            </p>
            <textarea
              rows={3}
              value={correction}
              onChange={(event) => onCorrection(event.target.value)}
              placeholder={"Make the opening more festive.\nKeep the product photo exactly as supplied.\nMake the voice more energetic."}
              className="mt-3 w-full rounded-xl border border-line bg-card px-4 py-3 outline-none focus:border-[var(--misa-cyan)]"
            />
            {showCorrection ? (
              <label className="mt-3 block text-sm">
                Or speak your correction
                <input
                  type="file"
                  accept="audio/*"
                  className="mt-2 w-full text-sm"
                  onChange={(event) => onCorrectionVoice(event.target.files?.[0] || null)}
                />
              </label>
            ) : (
              <button type="button" className="mt-2 text-xs text-[var(--success)] underline-offset-2 hover:underline" onClick={onToggleCorrection}>
                Add a voice note
              </button>
            )}
            <PrimaryButton
              type="button"
              className="mt-4"
              disabled={pending || !correction.trim()}
              onClick={onApplyCorrection}
            >
              {pending ? "Applying…" : "Apply change"}
            </PrimaryButton>
          </div>

          {project.preview_url ? (
            <p className="mt-4 text-sm">
              <Link href={`/brand/videos?id=${project.id}`} className="text-[var(--success)] underline-offset-2 hover:underline">
                Open this video in Projects
              </Link>
            </p>
          ) : null}

          {serious.length && !blocking.length ? (
            <label className="mt-6 flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                className="mt-1"
                checked={confirmSerious}
                onChange={(event) => setConfirmSerious(event.target.checked)}
              />
              I reviewed the high-confidence visual issues and still want to approve.
            </label>
          ) : null}

          <div className="mt-6 flex flex-col gap-3 sm:flex-row">
            <PrimaryButton
              type="button"
              disabled={
                pending ||
                Boolean(blocking.length) ||
                Boolean(failedGates.length) ||
                (Boolean(serious.length) && !confirmSerious && !blocking.length && !failedGates.length)
              }
              onClick={() => onApprove(Boolean(serious.length) && !blocking.length)}
            >
              {pending ? "Saving…" : blocking.length ? "Approve (blocked)" : "Approve video"}
            </PrimaryButton>
            <SecondaryButton type="button" onClick={onNew}>
              New video
            </SecondaryButton>
          </div>
          {blocking.length ? (
            <p className="mt-2 text-xs text-muted">
              {needsRerun ? "Run AI Review first. " : ""}
              Approval stays disabled until required checks complete.
            </p>
          ) : null}
        </div>
      </div>
      {gates.length ? (
        <section className="grid gap-4">
          <h3 className="font-medium">Scene identity and narration</h3>
          {gates.map((gate) => {
            const identity = gate.identity;
            const audio = gate.audio;
            const identityOn = Boolean(identity && identity.required !== false);
            const audioOn = audio?.required === true;
            const identityOk = identityPassed(identity);
            const audioOk = narrationPassed(audio);
            const failed = (identityOn && !identityOk) || (audioOn && !audioOk);
            const score = identityScoreLabel(identity);
            return (
              <article key={gate.scene_key} className="rounded-xl border border-line p-4">
                <h4 className="font-medium">{gate.label || gate.scene_key}</h4>
                {identityOn ? (
                  <div className="mt-3 grid gap-3 sm:grid-cols-2">
                    <figure className="rounded-xl border border-line p-3">
                      <p className="text-xs text-muted">Character reference</p>
                      {identity?.reference_url ? (
                        <img
                          src={identity.reference_url}
                          alt={identity.character_name || "Character reference"}
                          className="mt-2 h-40 w-full rounded-xl object-cover"
                        />
                      ) : (
                        <p className="mt-6 text-sm">Reference image missing</p>
                      )}
                      <figcaption className="mt-2 text-sm">{identity?.character_name || "Character"}</figcaption>
                    </figure>
                    <figure className="rounded-xl border border-line p-3">
                      <p className="text-xs text-muted">Generated scene</p>
                      {identity?.generated_face_url ? (
                        <img
                          src={identity.generated_face_url}
                          alt={`${gate.label || gate.scene_key} face`}
                          className="mt-2 h-40 w-full rounded-xl object-cover"
                        />
                      ) : (
                        <p className="mt-6 text-sm">Face not detected</p>
                      )}
                      <figcaption className="mt-2 text-sm">{gate.label || gate.scene_key}</figcaption>
                    </figure>
                  </div>
                ) : null}
                <dl className="mt-3 grid gap-1 text-sm">
                  {identityOn ? (
                    <div className="flex flex-wrap gap-3">
                      <dt>Identity</dt>
                      <dd>
                        {score ? `${score} ` : ""}
                        {identityOk ? "PASS" : "FAIL"}
                        {typeof identity?.threshold === "number"
                          ? ` · threshold ${Math.round(identity.threshold * 100)}%`
                          : ""}
                      </dd>
                    </div>
                  ) : null}
                  {audioOn ? (
                    <div className="flex flex-wrap gap-3">
                      <dt>Narration</dt>
                      <dd>{audioOk ? "PASS" : "FAIL"}</dd>
                    </div>
                  ) : null}
                </dl>
                {!identityOk && identityOn && identity?.reason ? (
                  <p className="mt-2 text-sm text-muted">{identity.reason}</p>
                ) : null}
                {!audioOk && audioOn && audio?.reason ? (
                  <p className="mt-1 text-sm text-muted">{audio.reason}</p>
                ) : null}
                {failed && onRegenerateScene ? (
                  <div className="mt-3">
                    <SecondaryButton type="button" onClick={() => onRegenerateScene(gate.scene_key)}>
                      Regenerate scene
                    </SecondaryButton>
                  </div>
                ) : null}
              </article>
            );
          })}
        </section>
      ) : null}
    </div>
  );
}
