"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { PageHead, StateBlock, inputClass, primaryButtonClass } from "@/components/agent/ui";
import {
  api,
  endpoints,
  type BrandAgentRow,
  type BrandAgentSearchResult,
  type BrandJoinRequest,
  type BrandTeam,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function BrandAgentsPage() {
  const { token } = useAuth();
  const [agents, setAgents] = useState<BrandAgentRow[]>([]);
  const [teams, setTeams] = useState<BrandTeam[]>([]);
  const [requests, setRequests] = useState<BrandJoinRequest[]>([]);
  const [teamId, setTeamId] = useState("");
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<BrandAgentSearchResult[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    if (!token) return;
    const agentUrl = teamId
      ? `${endpoints.brands.agents}?team=${teamId}${query ? `&q=${encodeURIComponent(query)}` : ""}`
      : `${endpoints.brands.agents}${query ? `?q=${encodeURIComponent(query)}` : ""}`;
    Promise.all([
      api<BrandAgentRow[]>(agentUrl, { token }),
      api<BrandTeam[]>(endpoints.brands.teams, { token }),
      api<BrandJoinRequest[]>(endpoints.brands.joinRequests, { token }),
    ])
      .then(([nextAgents, nextTeams, nextRequests]) => {
        setAgents(nextAgents);
        setTeams(nextTeams);
        setRequests(nextRequests);
        if (!teamId && nextTeams[0]) setTeamId(String(nextTeams[0].id));
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token, teamId, query]);

  useEffect(() => {
    load();
  }, [load]);

  async function searchAgents() {
    if (!token) return;
    const rows = await api<BrandAgentSearchResult[]>(
      endpoints.brands.agentSearch({ q: search, team: teamId }),
      { token },
    );
    setResults(rows);
  }

  async function invite(agentId: number) {
    if (!token || !teamId) return;
    await api(endpoints.brands.teamInvite(Number(teamId)), {
      method: "POST",
      token,
      body: JSON.stringify({ agent: agentId }),
    });
    setResults([]);
    setSearch("");
    load();
  }

  return (
    <div>
      <PageHead
        kicker="Agents"
        title="Team members and invitations"
        description="Search eligible agents, send invitations, and review incoming join requests. Agents see invitations in their workspace."
      />
      <StateBlock loading={loading} error={error}>
        <section className="rounded-2xl border border-line bg-card p-5">
          <h2 className="text-xl">Invite an agent</h2>
          <div className="mt-4 grid gap-3 md:grid-cols-[180px_1fr_auto]">
            <select className={inputClass} value={teamId} onChange={(event) => setTeamId(event.target.value)}>
              {teams.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
                </option>
              ))}
            </select>
            <input
              className={inputClass}
              placeholder="Search eligible agents"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <button type="button" className={primaryButtonClass} onClick={searchAgents} disabled={!teamId}>
              Search
            </button>
          </div>
          {results.length ? (
            <ul className="mt-4 divide-y divide-line rounded-xl border border-line">
              {results.map((agent) => (
                <li key={agent.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
                  <span>
                    {agent.name || agent.username} · {agent.email}
                  </span>
                  <button type="button" className="text-gold" onClick={() => invite(agent.id)}>
                    Invite
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </section>

        <section className="mt-10">
          <h2 className="text-xl">Join requests</h2>
          <div className="mt-4">
            <StateBlock
              loading={false}
              error=""
              empty={requests.length === 0}
              emptyTitle="No pending join requests"
            >
              <ul className="divide-y divide-line rounded-2xl border border-line bg-card">
                {requests.map((row) => (
                  <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-sm">
                    <span>
                      {row.agent_name} → {row.team_name}
                      {row.message ? ` · ${row.message}` : ""}
                    </span>
                    {row.can_review && token ? (
                      <span className="flex gap-3">
                        <button
                          type="button"
                          className="text-gold"
                          onClick={() =>
                            api(endpoints.brands.joinRequestApprove(row.id), { method: "POST", token }).then(load)
                          }
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            api(endpoints.brands.joinRequestReject(row.id), { method: "POST", token }).then(load)
                          }
                        >
                          Reject
                        </button>
                      </span>
                    ) : (
                      <span className="text-muted">{row.status}</span>
                    )}
                  </li>
                ))}
              </ul>
            </StateBlock>
          </div>
        </section>

        <section className="mt-10">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <h2 className="text-xl">Members</h2>
            <input
              className={`${inputClass} max-w-xs`}
              placeholder="Filter by name"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <div className="mt-4">
            <StateBlock
              loading={false}
              error=""
              empty={agents.length === 0}
              emptyTitle="No agents on your teams yet"
              emptyBody="Invite an agent or approve a join request."
            >
              <ul className="divide-y divide-line rounded-2xl border border-line bg-card">
                {agents.map((row) => (
                  <li key={`${row.id}-${row.team_id}`} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
                    <div>
                      <p>{row.agent_name}</p>
                      <p className="text-sm text-muted">
                        {row.team_name} · {row.status} · {row.agent_email}
                      </p>
                    </div>
                    <Link href={`/brand/teams/${row.team_id}`} className="text-sm text-gold">
                      View team
                    </Link>
                  </li>
                ))}
              </ul>
            </StateBlock>
          </div>
        </section>
      </StateBlock>
    </div>
  );
}
