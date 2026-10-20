"use client";

import { FormEvent, useMemo, useState } from "react";

import {
  CommissionBlock,
  Field,
  inputClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/agent/ui";
import { api, endpoints, type AgentProductDetail, type AgentTrackingLink } from "@/lib/api";

export function CreateTrackingLink({
  product,
  token,
  onCreated,
}: {
  product: AgentProductDetail;
  token: string;
  onCreated?: (link: AgentTrackingLink) => void;
}) {
  const [teamId, setTeamId] = useState(String(product.teams[0]?.id || ""));
  const [contentId, setContentId] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [link, setLink] = useState<AgentTrackingLink | null>(null);
  const [copied, setCopied] = useState(false);
  const commission = useMemo(
    () => product.commissions.find((item) => String(item.team_id) === teamId) || product.commissions[0] || null,
    [product.commissions, teamId],
  );

  if (!product.can_share) {
    return (
      <p className="rounded-2xl border border-dashed border-line bg-card px-5 py-6 text-sm text-muted">
        Join a team for this brand before creating a tracking link.
      </p>
    );
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const created = await api<AgentTrackingLink>(endpoints.agents.links, {
        method: "POST",
        token,
        body: JSON.stringify({
          product: product.id,
          team: Number(teamId),
          content: contentId ? Number(contentId) : null,
        }),
      });
      setLink(created);
      onCreated?.(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the tracking link.");
    } finally {
      setPending(false);
    }
  }

  async function copy() {
    if (!link) return;
    await navigator.clipboard.writeText(link.url);
    setCopied(true);
    try {
      await api(endpoints.agents.linkShareIntent(link.id), { method: "POST", token });
    } catch {
      // Copy still succeeded; share intent is best-effort telemetry.
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-2xl border border-line bg-card p-5">
      <h3 className="text-lg">Create tracking link</h3>
      <Field label="Team">
        <select className={inputClass} value={teamId} onChange={(event) => setTeamId(event.target.value)}>
          {product.teams.map((team) => (
            <option key={team.id} value={team.id}>
              {team.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Approved video / reel">
        <select className={inputClass} value={contentId} onChange={(event) => setContentId(event.target.value)}>
          <option value="">Product page only</option>
          {product.content.map((item) => (
            <option key={item.id} value={item.id}>
              Video #{item.id} · {item.status}
            </option>
          ))}
        </select>
      </Field>
      {commission ? (
        <CommissionBlock gross={commission.gross} fee={commission.platform_fee} net={commission.net} />
      ) : (
        <p className="text-sm text-muted">No commission rule is configured for this team yet.</p>
      )}
      {error ? <p className="text-sm text-error">{error}</p> : null}
      <button type="submit" disabled={pending || !teamId} className={primaryButtonClass}>
        {pending ? "Creating…" : "Create unique link"}
      </button>
      {link ? (
        <div className="rounded-xl border border-line bg-white p-4 text-sm">
          <p className="break-all font-medium">{link.url}</p>
          <p className="mt-2 text-muted">
            {link.product_name} · {link.team_name}
            {link.content_id ? ` · video #${link.content_id}` : ""}
          </p>
          <button type="button" className={`${secondaryButtonClass} mt-3`} onClick={copy}>
            {copied ? "Copied" : "Copy link"}
          </button>
          <p className="mt-2 text-xs text-muted">
            Copying records a share intent in MISA. It is not a confirmed social post.
          </p>
        </div>
      ) : null}
    </form>
  );
}
