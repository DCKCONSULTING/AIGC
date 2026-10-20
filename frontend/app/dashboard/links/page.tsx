"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  CommissionBlock,
  Field,
  inputClass,
  PageHead,
  secondaryButtonClass,
  StateBlock,
} from "@/components/agent/ui";
import { linkQuery, money } from "@/lib/agent";
import {
  api,
  endpoints,
  type AgentBrandCard,
  type AgentLinkFilters,
  type AgentProductCard,
  type AgentTeam,
  type AgentTrackingLink,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

const emptyFilters: AgentLinkFilters = {
  product: "",
  brand: "",
  team: "",
  campaign: "",
  status: "",
  date_from: "",
  date_to: "",
};

export default function AgentLinksPage() {
  const { token } = useAuth();
  const [filters, setFilters] = useState<AgentLinkFilters>(emptyFilters);
  const [applied, setApplied] = useState<AgentLinkFilters>(emptyFilters);
  const [links, setLinks] = useState<AgentTrackingLink[]>([]);
  const [products, setProducts] = useState<AgentProductCard[]>([]);
  const [brands, setBrands] = useState<AgentBrandCard[]>([]);
  const [teams, setTeams] = useState<AgentTeam[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    setLoading(true);
    Promise.all([
      api<AgentTrackingLink[]>(linkQuery(applied), { token }),
      api<AgentProductCard[]>(endpoints.agents.products, { token }),
      api<AgentBrandCard[]>(endpoints.agents.brands, { token }),
      api<AgentTeam[]>(endpoints.agents.teams, { token }),
    ])
      .then(([nextLinks, nextProducts, nextBrands, nextTeams]) => {
        setLinks(nextLinks);
        setProducts(nextProducts);
        setBrands(nextBrands);
        setTeams(nextTeams);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token, applied]);

  const campaigns = useMemo(
    () =>
      teams.flatMap((team) =>
        team.campaigns.map((campaign) => ({ id: campaign.id, name: `${team.name} · ${campaign.name}` })),
      ),
    [teams],
  );

  function apply(event: FormEvent) {
    event.preventDefault();
    setApplied(filters);
  }

  return (
    <div>
      <PageHead
        kicker="My Links"
        title="Tracking links"
        description="Unique backend-issued links. Filter by product, brand, team, campaign, status, and date."
      />
      <form onSubmit={apply} className="mb-8 grid gap-3 rounded-2xl border border-line bg-card p-5 md:grid-cols-3">
        <Field label="Product">
          <select
            className={inputClass}
            value={filters.product}
            onChange={(event) => setFilters((current) => ({ ...current, product: event.target.value }))}
          >
            <option value="">All</option>
            {products.map((product) => (
              <option key={product.id} value={product.id}>
                {product.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Brand">
          <select
            className={inputClass}
            value={filters.brand}
            onChange={(event) => setFilters((current) => ({ ...current, brand: event.target.value }))}
          >
            <option value="">All</option>
            {brands.map((brand) => (
              <option key={brand.id} value={brand.id}>
                {brand.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Team">
          <select
            className={inputClass}
            value={filters.team}
            onChange={(event) => setFilters((current) => ({ ...current, team: event.target.value }))}
          >
            <option value="">All</option>
            {teams.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Campaign">
          <select
            className={inputClass}
            value={filters.campaign}
            onChange={(event) => setFilters((current) => ({ ...current, campaign: event.target.value }))}
          >
            <option value="">All</option>
            {campaigns.map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Status">
          <select
            className={inputClass}
            value={filters.status}
            onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}
          >
            <option value="">All</option>
            <option value="active">Active</option>
            <option value="paused">Paused</option>
            <option value="revoked">Revoked</option>
          </select>
        </Field>
        <Field label="From">
          <input
            type="date"
            className={inputClass}
            value={filters.date_from}
            onChange={(event) => setFilters((current) => ({ ...current, date_from: event.target.value }))}
          />
        </Field>
        <Field label="To">
          <input
            type="date"
            className={inputClass}
            value={filters.date_to}
            onChange={(event) => setFilters((current) => ({ ...current, date_to: event.target.value }))}
          />
        </Field>
        <div className="flex items-end">
          <button type="submit" className={secondaryButtonClass}>
            Apply filters
          </button>
        </div>
      </form>
      <StateBlock
        loading={loading}
        error={error}
        empty={links.length === 0}
        emptyTitle="No tracking links"
        emptyBody="Create a unique link from a product page. Codes are issued by the backend."
      >
        <div className="space-y-4">
          {links.map((link) => (
            <Link
              key={link.id}
              href={`/dashboard/links/${link.id}`}
              className="block rounded-2xl border border-line bg-card p-5 hover:border-[var(--misa-blue)]"
            >
              <p className="break-all font-medium">{link.url}</p>
              <p className="mt-2 text-sm text-muted">
                {link.product_name} · {link.brand_name} · {link.team_name}
                {link.campaign_name ? ` · ${link.campaign_name}` : ""}
                {link.content_id ? ` · video #${link.content_id}` : ""}
              </p>
              <p className="mt-2 text-sm text-muted">
                Created {new Date(link.created_at).toLocaleString()} · {link.opens} opens · {link.unique_opens} unique ·{" "}
                {link.conversions} conversions · {money(link.earnings_net)} net
              </p>
              {link.commission ? (
                <div className="mt-3">
                  <CommissionBlock
                    gross={link.commission.gross}
                    fee={link.commission.platform_fee}
                    net={link.commission.net}
                  />
                </div>
              ) : null}
            </Link>
          ))}
        </div>
      </StateBlock>
    </div>
  );
}
