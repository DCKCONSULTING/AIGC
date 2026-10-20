"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { Field, PageHead, StateBlock, StatCard, inputClass, secondaryButtonClass } from "@/components/agent/ui";
import { money } from "@/lib/agent";
import {
  api,
  endpoints,
  type BrandAgentRow,
  type BrandCampaign,
  type BrandPerformance,
  type BrandTeam,
  type Product,
} from "@/lib/api";
import { performanceQuery } from "@/lib/brand";
import { useAuth } from "@/lib/auth";

const emptyFilters = {
  date_from: "",
  date_to: "",
  team: "",
  agent: "",
  product: "",
  campaign: "",
};

export default function BrandPerformancePage() {
  const { token } = useAuth();
  const [data, setData] = useState<BrandPerformance | null>(null);
  const [teams, setTeams] = useState<BrandTeam[]>([]);
  const [agents, setAgents] = useState<BrandAgentRow[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [campaigns, setCampaigns] = useState<BrandCampaign[]>([]);
  const [filters, setFilters] = useState(emptyFilters);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    if (!token) return;
    api<BrandPerformance>(performanceQuery(filters), { token })
      .then((payload) => {
        setData(payload);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token, filters]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      api<BrandTeam[]>(endpoints.brands.teams, { token }),
      api<BrandAgentRow[]>(endpoints.brands.agents, { token }),
      api<Product[]>(endpoints.brands.products, { token }),
      api<BrandCampaign[]>(endpoints.brands.campaigns, { token }),
    ])
      .then(([nextTeams, nextAgents, nextProducts, nextCampaigns]) => {
        setTeams(nextTeams);
        setAgents(nextAgents);
        setProducts(nextProducts);
        setCampaigns(nextCampaigns);
      })
      .catch(() => undefined);
  }, [token]);

  function onFilter(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    load();
  }

  return (
    <div>
      <PageHead
        kicker="Performance"
        title="Recorded agent activity"
        description="These figures are counted from tracking events and commission snapshots. Conversions stay at zero until a conversion is recorded."
      />
      <form onSubmit={onFilter} className="mb-8 grid gap-3 rounded-2xl border border-line bg-card p-5 md:grid-cols-3">
        <Field label="From">
          <input
            type="date"
            className={inputClass}
            value={filters.date_from}
            onChange={(event) => setFilters({ ...filters, date_from: event.target.value })}
          />
        </Field>
        <Field label="To">
          <input
            type="date"
            className={inputClass}
            value={filters.date_to}
            onChange={(event) => setFilters({ ...filters, date_to: event.target.value })}
          />
        </Field>
        <Field label="Team">
          <select
            className={inputClass}
            value={filters.team}
            onChange={(event) => setFilters({ ...filters, team: event.target.value })}
          >
            <option value="">All teams</option>
            {teams.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Agent">
          <select
            className={inputClass}
            value={filters.agent}
            onChange={(event) => setFilters({ ...filters, agent: event.target.value })}
          >
            <option value="">All agents</option>
            {agents.map((agent) => (
              <option key={`${agent.id}-${agent.agent_id}`} value={agent.agent_id}>
                {agent.agent_name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Product">
          <select
            className={inputClass}
            value={filters.product}
            onChange={(event) => setFilters({ ...filters, product: event.target.value })}
          >
            <option value="">All products</option>
            {products.map((product) => (
              <option key={product.id} value={product.id}>
                {product.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Campaign">
          <select
            className={inputClass}
            value={filters.campaign}
            onChange={(event) => setFilters({ ...filters, campaign: event.target.value })}
          >
            <option value="">All campaigns</option>
            {campaigns.map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.name}
              </option>
            ))}
          </select>
        </Field>
        <div className="flex items-end gap-3">
          <button type="submit" className={secondaryButtonClass}>
            Apply filters
          </button>
          <button type="button" className={secondaryButtonClass} onClick={() => setFilters(emptyFilters)}>
            Reset
          </button>
        </div>
      </form>
      <StateBlock loading={loading} error={error}>
        {data ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard label="Total agents" value={data.total_agents} />
              <StatCard label="Active agents" value={data.active_agents} />
              <StatCard label="Links" value={data.links} />
              <StatCard label="Opens" value={data.opens} />
              <StatCard label="Unique opens" value={data.unique_opens ?? 0} />
              <StatCard label="Conversions" value={data.conversions} />
              <StatCard label="Gross commissions" value={money(data.gross_commissions)} />
              <StatCard label="Platform fees" value={money(data.platform_fees)} />
              <StatCard label="Agent payouts" value={money(data.agent_payouts)} />
            </div>
            {data.links === 0 && data.conversions === 0 ? (
              <p className="mt-8 rounded-2xl border border-dashed border-line bg-card px-5 py-10 text-center text-muted">
                No recorded activity for this filter. Empty values are zeros, not estimates.
              </p>
            ) : null}
            {data.by_product && data.by_product.length ? (
              <section className="mt-10">
                <h2 className="text-xl">By product</h2>
                <ul className="mt-4 divide-y divide-line rounded-2xl border border-line bg-card">
                  {data.by_product.map((row) => (
                    <li key={row.id} className="flex flex-wrap justify-between gap-3 px-5 py-3 text-sm">
                      <span>{row.name}</span>
                      <span className="text-muted">
                        {row.opens} opens · {row.unique_opens ?? 0} unique · {row.conversions} conversions
                      </span>
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
