"use client";

import { useState } from "react";

import type { VideoProject } from "@/lib/api";
import { qaCardDetail, qaLayerSummary, qaNeedsRerun, qaStatusLabel, releaseBlockingIssues, seriousQaIssues } from "@/lib/studio";
import { ChoiceButton, PrimaryButton, SecondaryButton, StatusMark } from "./ui";
import { VideoStage } from "./VideoStage";

export function ApprovalControls({
  project,
  approved,
  pending,
  credits,
  publishPlatform,
  publishAuthorized,
  publishNote,
  onApprove,
  onExport,
  onNew,
  onPlatform,
  onAuthorized,
  onPublish,
  onRerunQa,
}: {
  project: VideoProject;
  approved: boolean;
  pending: boolean;
  credits: { video: number; account: number };
  publishPlatform: string;
  publishAuthorized: boolean;
  publishNote: string;
  onApprove: (confirm?: boolean) => void;
  onExport: () => void;
  onNew: () => void;
  onPlatform: (value: string) => void;
  onAuthorized: (value: boolean) => void;
  onPublish: () => void;
  onRerunQa?: () => void;
}) {
  const layers = qaLayerSummary(project.qa_results?.layers, project.qa_results?.checks);
  const serious = seriousQaIssues(project.qa_results?.checks);
  const blocking = project.qa_results?.release_blocking?.length
    ? project.qa_results.release_blocking
    : releaseBlockingIssues(project.qa_results?.checks, {
        hasPreview: Boolean(project.preview_url || project.final_url),
      });
  const [confirmSerious, setConfirmSerious] = useState(false);
  const needsRerun = qaNeedsRerun(project.qa_results?.checks);

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
      <VideoStage project={project} />
      <div>
        {approved ? (
          <>
            <p className="text-sm font-medium text-[var(--success)]">Approved</p>
            <h2 className="mt-2 font-serif text-3xl text-foreground">Export video</h2>
            <p className="mt-2 text-sm text-muted">Download the file, or start another version.</p>
          </>
        ) : (
          <>
            <h2 className="font-serif text-3xl text-foreground">
              {blocking.length ? "Checks required" : "Ready for review"}
            </h2>
            <p className="mt-2 text-sm text-muted">
              Approve if the product, price, and captions look right. A check that did not run is NOT CHECKED, not a pass.
            </p>
            <ul className="mt-6 grid gap-2">
              {layers.map((item) => (
                <li key={item.key} className="flex items-start gap-3 text-sm">
                  <StatusMark status={item.mark} />
                  <span>
                    {item.label}: {qaStatusLabel(item.mark)}
                    {item.mark === "not_checked" || item.mark === "skipped"
                      ? ` — ${qaCardDetail(item)}`
                      : item.mark === "warning"
                        ? ` — ${qaCardDetail(item)}`
                        : item.mark === "failed"
                          ? ` — ${qaCardDetail(item)}`
                          : item.hasConfidence
                            ? ` — ${Math.round(item.confidence * 100)}% confidence`
                            : ""}
                  </span>
                </li>
              ))}
            </ul>
            {blocking.length ? (
              <div className="mt-5 rounded-xl border border-[#ffd0e2] bg-[#fff0f6] p-4 text-sm">
                <p className="font-medium">Approval blocked</p>
                {blocking.map((item, index) => (
                  <p key={`${item.name}-${index}`} className="mt-2">
                    {qaStatusLabel(item.status || "not_checked")}: {item.detail}
                  </p>
                ))}
                <p className="mt-2 text-muted">
                  Required checks have not completed, or a release check failed.
                </p>
              </div>
            ) : null}
            {needsRerun && onRerunQa ? (
              <div className="mt-5">
                <PrimaryButton type="button" disabled={pending} onClick={onRerunQa}>
                  {pending ? "AI review in progress…" : "Run AI Review"}
                </PrimaryButton>
              </div>
            ) : null}
            {serious.length && !blocking.length ? (
              <label className="mt-5 flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={confirmSerious}
                  onChange={(event) => setConfirmSerious(event.target.checked)}
                />
                I reviewed the high-confidence visual issues and still want to approve.
              </label>
            ) : null}
            <PrimaryButton
              type="button"
              className="mt-6"
              disabled={pending || Boolean(blocking.length) || (Boolean(serious.length) && !confirmSerious && !blocking.length)}
              onClick={() => onApprove(Boolean(serious.length) && !blocking.length)}
            >
              {pending ? "Saving…" : blocking.length ? "Approve (blocked)" : "Approve video"}
            </PrimaryButton>
            {blocking.length ? (
              <p className="mt-2 text-xs text-muted">Approval stays disabled until required checks complete.</p>
            ) : null}
          </>
        )}
        {approved ? (
          <div className="mt-6 flex flex-wrap gap-3">
            <a
              href={project.export_url || project.final_url || project.preview_url}
              download
              className="inline-flex h-12 items-center rounded-full bg-[linear-gradient(110deg,#0874f9,#1764ef_55%,#7658f4)] px-6 text-sm font-medium text-white"
            >
              Download
            </a>
            <SecondaryButton type="button" disabled={pending} onClick={onExport}>
              {pending ? "Exporting…" : "Export"}
            </SecondaryButton>
            <SecondaryButton type="button" onClick={onNew}>
              Create another version
            </SecondaryButton>
          </div>
        ) : null}

        {approved ? (
        <div className="mt-10 rounded-2xl border border-line bg-background p-5">
          <h3 className="font-medium">Publish</h3>
          <p className="mt-2 text-sm text-muted">Nothing is posted until you authorize it. This only saves the authorization.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {[
              { id: "tiktok", label: "TikTok" },
              { id: "instagram", label: "Instagram" },
              { id: "facebook", label: "Facebook" },
            ].map((platform) => (
              <ChoiceButton
                key={platform.id}
                selected={publishPlatform === platform.id}
                title={platform.label}
                onClick={() => onPlatform(platform.id)}
              />
            ))}
          </div>
          <label className="mt-4 flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={publishAuthorized}
              onChange={(event) => onAuthorized(event.target.checked)}
            />
            I authorize this post
          </label>
          <PrimaryButton
            type="button"
            className="mt-5"
            disabled={pending || !publishPlatform || !publishAuthorized}
            onClick={onPublish}
          >
            {pending ? "Saving…" : "Authorize post"}
          </PrimaryButton>
          {publishNote ? <p className="mt-3 text-sm text-muted">{publishNote}</p> : null}
        </div>
        ) : null}

        <p className="mt-8 text-xs text-muted">
          This video · Estimated usage: {credits.video || 1} credits
          <br />
          Account usage: {credits.account} credits
        </p>
      </div>
    </div>
  );
}
