"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { CommissionBlock, PageHead, secondaryButtonClass, StateBlock } from "@/components/agent/ui";
import { eventLabel, money } from "@/lib/agent";
import { api, endpoints, type AgentTrackingLink } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AgentLinkDetailPage() {
  const params = useParams<{ id: string }>();
  const { token } = useAuth();
  const [link, setLink] = useState<AgentTrackingLink | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!token || !params.id) return;
    api<AgentTrackingLink>(endpoints.agents.linkDetail(Number(params.id)), { token })
      .then((payload) => {
        setLink(payload);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token, params.id]);

  async function copy() {
    if (!link || !token) return;
    await navigator.clipboard.writeText(link.url);
    setCopied(true);
    try {
      await api(endpoints.agents.linkShareIntent(link.id), { method: "POST", token });
    } catch {
      // Copy still succeeded.
    }
  }

  return (
    <div>
      <StateBlock loading={loading} error={error}>
        {link ? (
          <>
            <PageHead kicker={link.status} title={link.product_name} description={link.url} />
            <div className="grid gap-4 sm:grid-cols-2">
              <p className="rounded-2xl border border-line bg-card p-4 text-sm">Product: {link.product_name}</p>
              <p className="rounded-2xl border border-line bg-card p-4 text-sm">
                Content: {link.content_id ? `Video #${link.content_id}` : "Product page"}
              </p>
              <p className="rounded-2xl border border-line bg-card p-4 text-sm">Team: {link.team_name}</p>
              <p className="rounded-2xl border border-line bg-card p-4 text-sm">
                Created: {new Date(link.created_at).toLocaleString()}
              </p>
            </div>
            <div className="mt-6 grid gap-4 sm:grid-cols-4">
              <p className="rounded-2xl border border-line bg-card p-4 text-sm">Opens: {link.opens}</p>
              <p className="rounded-2xl border border-line bg-card p-4 text-sm">Unique opens: {link.unique_opens}</p>
              <p className="rounded-2xl border border-line bg-card p-4 text-sm">Conversions: {link.conversions}</p>
              <p className="rounded-2xl border border-line bg-card p-4 text-sm">Earnings: {money(link.earnings_net)}</p>
            </div>
            <div className="mt-6 rounded-2xl border border-line bg-card p-5">
              <h2 className="text-lg">Commission</h2>
              {link.commission ? (
                <div className="mt-3">
                  <CommissionBlock
                    gross={link.commission.gross}
                    fee={link.commission.platform_fee}
                    net={link.commission.net}
                  />
                </div>
              ) : (
                <p className="mt-3 text-sm text-muted">No commission rule is configured.</p>
              )}
              <button type="button" className={`${secondaryButtonClass} mt-4`} onClick={copy}>
                {copied ? "Copied" : "Copy public link"}
              </button>
              <p className="mt-2 text-xs text-muted">
                Copying records a share intent in MISA, not a confirmed social post.
              </p>
            </div>
            <section className="mt-8">
              <h2 className="text-xl">Activity</h2>
              <div className="mt-4">
                <StateBlock
                  loading={false}
                  error=""
                  empty={!link.activity?.length}
                  emptyTitle="No events yet"
                >
                  <ul className="divide-y divide-line rounded-2xl border border-line bg-card">
                    {(link.activity || []).map((event) => (
                      <li key={event.id} className="flex flex-wrap justify-between gap-2 px-5 py-3 text-sm">
                        <span>{event.label || eventLabel(event.event_type)}</span>
                        <span className="text-muted">{new Date(event.created_at).toLocaleString()}</span>
                      </li>
                    ))}
                  </ul>
                </StateBlock>
              </div>
            </section>
          </>
        ) : null}
      </StateBlock>
    </div>
  );
}
