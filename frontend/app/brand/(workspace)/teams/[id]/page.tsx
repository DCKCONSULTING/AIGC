"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";

import {
  Field,
  PageHead,
  StateBlock,
  inputClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/agent/ui";
import { CommissionLayers } from "@/components/brand/CommissionLayers";
import { money } from "@/lib/agent";
import {
  api,
  endpoints,
  type BrandAgentSearchResult,
  type BrandCommissionPreview,
  type BrandTeamDetail,
  type Product,
} from "@/lib/api";
import { previewQuery } from "@/lib/brand";
import { useAuth } from "@/lib/auth";

const MEMBER_SORTS = [
  { key: "agent", label: "Agent" },
  { key: "status", label: "Status" },
  { key: "joined_at", label: "Joined" },
  { key: "links", label: "Links" },
  { key: "opens", label: "Opens" },
  { key: "unique_opens", label: "Unique opens" },
  { key: "conversions", label: "Conversions" },
  { key: "gross_commission", label: "Gross" },
  { key: "misa_fee", label: "MISA fee" },
  { key: "agent_net_earnings", label: "Agent net" },
];

export default function BrandTeamDetailPage() {
  const params = useParams<{ id: string }>();
  const { token } = useAuth();
  const teamId = Number(params.id);
  const [data, setData] = useState<BrandTeamDetail | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("-joined_at");
  const [productId, setProductId] = useState("");
  const [preview, setPreview] = useState<BrandCommissionPreview | null>(null);
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<BrandAgentSearchResult[]>([]);
  const [pending, setPending] = useState(false);

  const load = useCallback(() => {
    if (!token || !teamId) return;
    const params: Record<string, string> = {};
    if (statusFilter) params.status = statusFilter;
    if (query) params.q = query;
    if (sort) params.sort = sort;
    if (productId) params.product = productId;
    api<BrandTeamDetail>(endpoints.brands.teamDetail(teamId, params), { token })
      .then((payload) => {
        setData(payload);
        setName(payload.team.name);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token, teamId, statusFilter, query, sort, productId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!token) return;
    api<Product[]>(endpoints.brands.products, { token }).then(setProducts).catch(() => undefined);
  }, [token]);

  useEffect(() => {
    if (!token || !productId) {
      setPreview(null);
      return;
    }
    api<BrandCommissionPreview>(previewQuery({ product: productId, team: String(teamId) }), { token })
      .then(setPreview)
      .catch(() => setPreview(null));
  }, [token, productId, teamId]);

  const pendingRequests = useMemo(
    () => data?.join_requests.filter((row) => row.can_review) || [],
    [data],
  );

  async function saveName(event: FormEvent) {
    event.preventDefault();
    if (!token || !data) return;
    setPending(true);
    try {
      await api(endpoints.brands.teamDetail(data.team.id), {
        method: "PATCH",
        token,
        body: JSON.stringify({ name }),
      });
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  async function toggleStatus() {
    if (!token || !data) return;
    const next = data.team.status === "active" ? "paused" : "active";
    await api(endpoints.brands.teamDetail(data.team.id), {
      method: "PATCH",
      token,
      body: JSON.stringify({ status: next }),
    });
    load();
  }

  async function searchAgents() {
    if (!token) return;
    const rows = await api<BrandAgentSearchResult[]>(
      endpoints.brands.agentSearch({ q: search, team: String(teamId) }),
      { token },
    );
    setResults(rows);
  }

  async function invite(agentId: number) {
    if (!token) return;
    await api(endpoints.brands.teamInvite(teamId), {
      method: "POST",
      token,
      body: JSON.stringify({ agent: agentId }),
    });
    setResults([]);
    setSearch("");
    load();
  }

  async function setMemberStatus(id: number, status: string) {
    if (!token) return;
    await api(endpoints.brands.membership(id), {
      method: "PATCH",
      token,
      body: JSON.stringify({ status }),
    });
    load();
  }

  return (
    <div>
      <StateBlock loading={loading} error={error}>
        {data ? (
          <>
            <PageHead
              kicker={data.team.brand_name}
              title={data.team.name}
              description={data.team.description || "Team members, invitations, and recorded performance."}
            />
            <div className="flex flex-wrap gap-3">
              <form onSubmit={saveName} className="flex flex-wrap gap-3">
                <input className={inputClass} value={name} onChange={(event) => setName(event.target.value)} />
                <button type="submit" className={secondaryButtonClass} disabled={pending}>
                  Rename
                </button>
              </form>
              <button type="button" className={secondaryButtonClass} onClick={toggleStatus}>
                {data.team.status === "active" ? "Deactivate team" : "Activate team"}
              </button>
              <span className="self-center text-sm text-muted">Status: {data.team.status}</span>
            </div>

            <section className="mt-8">
              <h2 className="text-xl">Invite agents</h2>
              <div className="mt-3 flex flex-wrap gap-3">
                <input
                  className={`${inputClass} max-w-sm`}
                  placeholder="Search name, username, or email"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
                <button type="button" className={primaryButtonClass} onClick={searchAgents}>
                  Search
                </button>
              </div>
              {results.length ? (
                <ul className="mt-3 divide-y divide-line rounded-2xl border border-line bg-card">
                  {results.map((agent) => (
                    <li key={agent.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 text-sm">
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

            <section className="mt-8">
              <h2 className="text-xl">Join requests</h2>
              <div className="mt-3">
                <StateBlock
                  loading={false}
                  error=""
                  empty={pendingRequests.length === 0}
                  emptyTitle="No pending requests"
                >
                  <ul className="divide-y divide-line rounded-2xl border border-line bg-card">
                    {pendingRequests.map((row) => (
                      <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-sm">
                        <span>
                          {row.agent_name} · {row.agent_email}
                          {row.message ? ` · ${row.message}` : ""}
                        </span>
                        <span className="flex gap-3">
                          <button
                            type="button"
                            className="text-gold"
                            onClick={() =>
                              token &&
                              api(endpoints.brands.joinRequestApprove(row.id), { method: "POST", token }).then(load)
                            }
                          >
                            Approve
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              token &&
                              api(endpoints.brands.joinRequestReject(row.id), { method: "POST", token }).then(load)
                            }
                          >
                            Reject
                          </button>
                        </span>
                      </li>
                    ))}
                  </ul>
                </StateBlock>
              </div>
            </section>

            <section className="mt-8">
              <h2 className="text-xl">Pending invitations</h2>
              <div className="mt-3">
                <StateBlock
                  loading={false}
                  error=""
                  empty={(data.invitations || []).filter((row) => row.can_cancel).length === 0}
                  emptyTitle="No pending invitations"
                >
                  <ul className="divide-y divide-line rounded-2xl border border-line bg-card">
                    {data.invitations
                      .filter((row) => row.can_cancel)
                      .map((row) => (
                        <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-sm">
                          <span>
                            {row.agent_name || row.agent_username} · {row.agent_email} · {row.status}
                          </span>
                          <button
                            type="button"
                            onClick={() =>
                              token &&
                              api(endpoints.brands.invitationCancel(row.id), { method: "POST", token }).then(load)
                            }
                          >
                            Cancel invite
                          </button>
                        </li>
                      ))}
                  </ul>
                </StateBlock>
              </div>
            </section>

            <section className="mt-8">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <h2 className="text-xl">Members</h2>
                <div className="flex flex-wrap gap-3">
                  <Field label="Status">
                    <select className={inputClass} value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                      <option value="">All</option>
                      <option value="active">Active</option>
                      <option value="suspended">Suspended</option>
                      <option value="removed">Removed</option>
                    </select>
                  </Field>
                  <Field label="Search">
                    <input className={inputClass} value={query} onChange={(event) => setQuery(event.target.value)} />
                  </Field>
                  <Field label="Product for commission">
                    <select className={inputClass} value={productId} onChange={(event) => setProductId(event.target.value)}>
                      <option value="">None</option>
                      {products.map((product) => (
                        <option key={product.id} value={product.id}>
                          {product.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
              </div>
              {preview ? <div className="mt-4"><CommissionLayers preview={preview} /></div> : null}
              <div className="mt-4 overflow-x-auto rounded-2xl border border-line bg-card">
                <table className="min-w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-line text-xs uppercase tracking-[0.12em] text-muted">
                      {MEMBER_SORTS.map((column) => (
                        <th key={column.key} className="px-4 py-3">
                          <button type="button" onClick={() => setSort(sort === column.key ? `-${column.key}` : column.key)}>
                            {column.label}
                          </button>
                        </th>
                      ))}
                      <th className="px-4 py-3">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.members.map((member) => (
                      <tr key={member.id} className="border-b border-line last:border-0">
                        <td className="px-4 py-3">
                          <div>{member.agent_name}</div>
                          <div className="text-xs text-muted">{member.agent_email}</div>
                        </td>
                        <td className="px-4 py-3">{member.status}</td>
                        <td className="px-4 py-3">{new Date(member.joined_at).toLocaleDateString()}</td>
                        <td className="px-4 py-3">{member.links}</td>
                        <td className="px-4 py-3">{member.opens}</td>
                        <td className="px-4 py-3">{member.unique_opens ?? 0}</td>
                        <td className="px-4 py-3">{member.conversions}</td>
                        <td className="px-4 py-3">{money(member.gross_commission)}</td>
                        <td className="px-4 py-3">{money(member.misa_fee)}</td>
                        <td className="px-4 py-3">{money(member.agent_net_earnings)}</td>
                        <td className="px-4 py-3">
                          <div className="flex flex-col gap-1">
                            {member.status === "active" ? (
                              <button type="button" onClick={() => setMemberStatus(member.id, "suspended")}>
                                Suspend
                              </button>
                            ) : (
                              <button type="button" onClick={() => setMemberStatus(member.id, "active")}>
                                Activate
                              </button>
                            )}
                            {member.status !== "removed" ? (
                              <button type="button" onClick={() => setMemberStatus(member.id, "removed")}>
                                Remove
                              </button>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {data.members.length === 0 ? (
                  <p className="px-5 py-10 text-center text-muted">No members match this filter.</p>
                ) : null}
              </div>
            </section>
            <Link href="/brand/teams" className="mt-8 inline-block text-sm text-gold">
              Back to teams
            </Link>
          </>
        ) : null}
      </StateBlock>
    </div>
  );
}
