"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { PageHead, StateBlock, StatCard } from "@/components/agent/ui";
import { emptyDashboard, eventLabel, money } from "@/lib/agent";
import { api, endpoints, type AgentDashboard } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function DashboardPage() {
  const { token, user, actingAccount } = useAuth();
  const [data, setData] = useState<AgentDashboard | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const name = actingAccount?.name || user?.name || "agent";

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    api<AgentDashboard>(endpoints.agents.dashboard, { token })
      .then((payload) => {
        setData(payload);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token]);

  const empty = data ? emptyDashboard(data) : { activity: true, products: true, teams: true };
  const currency = data?.currency || "USD";

  return (
    <div>
      <PageHead
        kicker="Dashboard"
        title={`Welcome, ${name}.`}
        description="Live opens, conversions, and earnings from your tracking links. Empty sections mean the backend has no events yet."
      />
      <StateBlock loading={loading} error={error}>
        {data ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard label="Total opens" value={data.total_opens} />
              <StatCard label="Unique opens" value={data.unique_opens} />
              <StatCard label="Total conversions" value={data.total_conversions} />
              <StatCard label="Gross commission" value={money(data.gross_commission, currency)} />
              <StatCard label="MISA fees" value={money(data.platform_fees, currency)} />
              <StatCard label="Net earnings" value={money(data.net_earnings, currency)} />
              <StatCard label="Available balance" value={money(data.available_balance, currency)} />
              <StatCard label="Pending balance" value={money(data.pending_balance, currency)} />
            </div>

            <section className="mt-10">
              <h2 className="text-xl text-[var(--misa-navy)]">Recent activity</h2>
              <div className="mt-4">
                <StateBlock
                  loading={false}
                  error=""
                  empty={empty.activity}
                  emptyTitle="No tracked activity yet"
                  emptyBody="Opens, clicks, conversions, and in-app copy events will appear here after they are recorded."
                >
                  <ul className="divide-y divide-line rounded-2xl border border-line bg-card">
                    {data.recent_activity.map((event) => (
                      <li key={event.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 text-sm">
                        <span>{event.label || eventLabel(event.event_type)}</span>
                        <span className="text-muted">
                          {event.link_code} · {new Date(event.created_at).toLocaleString()}
                        </span>
                      </li>
                    ))}
                  </ul>
                </StateBlock>
              </div>
            </section>

            <section className="mt-10 grid gap-8 lg:grid-cols-2">
              <div>
                <h2 className="text-xl text-[var(--misa-navy)]">Top products</h2>
                <div className="mt-4">
                  <StateBlock
                    loading={false}
                    error=""
                    empty={empty.products}
                    emptyTitle="No product performance yet"
                    emptyBody="Products appear here after your links record opens or conversions."
                  >
                    <ul className="space-y-3">
                      {data.top_products.map((product) => (
                        <li key={product.id} className="rounded-2xl border border-line bg-card p-4">
                          <Link href={`/dashboard/products/${product.id}`} className="font-medium hover:text-gold">
                            {product.name}
                          </Link>
                          <p className="mt-1 text-sm text-muted">
                            {product.brand_name} · {product.opens} opens · {product.conversions} conversions
                          </p>
                        </li>
                      ))}
                    </ul>
                  </StateBlock>
                </div>
              </div>
              <div>
                <h2 className="text-xl text-[var(--misa-navy)]">Active teams</h2>
                <div className="mt-4">
                  <StateBlock
                    loading={false}
                    error=""
                    empty={empty.teams}
                    emptyTitle="No active teams"
                    emptyBody="Join a brand team to start distributing products."
                  >
                    <ul className="space-y-3">
                      {data.active_teams.map((team) => (
                        <li key={team.id} className="rounded-2xl border border-line bg-card p-4">
                          <Link href={`/dashboard/teams/${team.id}`} className="font-medium hover:text-gold">
                            {team.name}
                          </Link>
                          <p className="mt-1 text-sm text-muted">{team.brand_name}</p>
                        </li>
                      ))}
                    </ul>
                  </StateBlock>
                </div>
              </div>
            </section>
          </>
        ) : null}
      </StateBlock>
    </div>
  );
}
