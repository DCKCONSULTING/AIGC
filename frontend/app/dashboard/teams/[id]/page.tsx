"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { TeamActions } from "@/components/agent/TeamActions";
import { PageHead, StateBlock } from "@/components/agent/ui";
import { api, endpoints, type AgentTeam } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AgentTeamDetailPage() {
  const params = useParams<{ id: string }>();
  const { token } = useAuth();
  const [team, setTeam] = useState<AgentTeam | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    if (!token || !params.id) return;
    api<AgentTeam>(endpoints.agents.teamDetail(Number(params.id)), { token })
      .then((payload) => {
        setTeam(payload);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token, params.id]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <StateBlock loading={loading} error={error}>
        {team ? (
          <>
            <PageHead kicker={team.brand_name} title={team.name} description={team.description} />
            <div className="rounded-2xl border border-line bg-card p-6">
              <p className="text-sm text-muted">
                Status: {team.status} · Members: {team.member_count}
              </p>
              <div className="mt-4">{token ? <TeamActions team={team} token={token} onChange={load} /> : null}</div>
              <Link href={`/dashboard/brands/${team.brand_id}`} className="mt-4 inline-block text-sm text-gold">
                View brand
              </Link>
            </div>
            {team.campaigns.length ? (
              <section className="mt-8">
                <h2 className="text-xl">Campaigns</h2>
                <ul className="mt-3 space-y-2 text-sm">
                  {team.campaigns.map((campaign) => (
                    <li key={campaign.id} className="rounded-xl border border-line bg-card px-4 py-3">
                      {campaign.name} · {campaign.status}
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
          </>
        ) : null}
      </StateBlock>
    </div>
  );
}
