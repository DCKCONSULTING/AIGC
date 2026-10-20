"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { TeamActions } from "@/components/agent/TeamActions";
import { PageHead, StateBlock } from "@/components/agent/ui";
import { api, endpoints, type AgentInvitation, type AgentJoinRequest, type AgentTeam } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AgentTeamsPage() {
  const { token } = useAuth();
  const [teams, setTeams] = useState<AgentTeam[]>([]);
  const [requests, setRequests] = useState<AgentJoinRequest[]>([]);
  const [invitations, setInvitations] = useState<AgentInvitation[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    if (!token) return;
    Promise.all([
      api<AgentTeam[]>(endpoints.agents.teams, { token }),
      api<AgentJoinRequest[]>(endpoints.agents.joinRequests, { token }),
      api<AgentInvitation[]>(endpoints.agents.invitations, { token }),
    ])
      .then(([nextTeams, nextRequests, nextInvites]) => {
        setTeams(nextTeams);
        setRequests(nextRequests);
        setInvitations(nextInvites);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <PageHead
        kicker="My Teams"
        title="Teams, requests, and invitations"
        description="Request to join from a brand page, cancel a pending request, or accept or decline an invitation."
      />
      <StateBlock loading={loading} error={error}>
        <h2 className="text-xl">Your teams</h2>
        <div className="mt-4">
          <StateBlock
            loading={false}
            error=""
            empty={teams.length === 0}
            emptyTitle="No teams yet"
            emptyBody="Browse brands to request access or wait for an invitation."
          >
            <div className="space-y-4">
              {teams.map((team) => (
                <div key={team.id} className="rounded-2xl border border-line bg-card p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <Link href={`/dashboard/teams/${team.id}`} className="text-lg hover:text-gold">
                        {team.name}
                      </Link>
                      <p className="mt-1 text-sm text-muted">{team.brand_name}</p>
                    </div>
                    {token ? <TeamActions team={team} token={token} onChange={load} /> : null}
                  </div>
                </div>
              ))}
            </div>
          </StateBlock>
        </div>

        <h2 className="mt-10 text-xl">Join requests</h2>
        <div className="mt-4">
          <StateBlock
            loading={false}
            error=""
            empty={requests.length === 0}
            emptyTitle="No join requests"
          >
            <ul className="divide-y divide-line rounded-2xl border border-line bg-card">
              {requests.map((row) => (
                <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-sm">
                  <span>
                    {row.team_name} · {row.brand_name} · {row.status}
                  </span>
                  {row.can_cancel && token ? (
                    <button
                      type="button"
                      className="text-gold"
                      onClick={() =>
                        api(endpoints.agents.joinRequestCancel(row.id), { method: "POST", token }).then(load)
                      }
                    >
                      Cancel
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          </StateBlock>
        </div>

        <h2 className="mt-10 text-xl">Invitations</h2>
        <div className="mt-4">
          <StateBlock
            loading={false}
            error=""
            empty={invitations.length === 0}
            emptyTitle="No invitations"
          >
            <ul className="divide-y divide-line rounded-2xl border border-line bg-card">
              {invitations.map((row) => (
                <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-sm">
                  <span>
                    {row.team_name} · {row.brand_name} · {row.status}
                  </span>
                  {row.can_accept && token ? (
                    <span className="flex gap-3">
                      <button
                        type="button"
                        className="text-gold"
                        onClick={() =>
                          api(endpoints.agents.invitationAccept(row.id), { method: "POST", token }).then(load)
                        }
                      >
                        Accept
                      </button>
                      {row.can_decline ? (
                        <button
                          type="button"
                          onClick={() =>
                            api(endpoints.agents.invitationDecline(row.id), { method: "POST", token }).then(load)
                          }
                        >
                          Decline
                        </button>
                      ) : null}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </StateBlock>
        </div>
      </StateBlock>
    </div>
  );
}
