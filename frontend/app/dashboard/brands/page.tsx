"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { PageHead, StateBlock } from "@/components/agent/ui";
import { api, endpoints, type AgentBrandCard } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AgentBrandsPage() {
  const { token } = useAuth();
  const [brands, setBrands] = useState<AgentBrandCard[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    api<AgentBrandCard[]>(endpoints.agents.brands, { token })
      .then((rows) => {
        setBrands(rows);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token]);

  return (
    <div>
      <PageHead
        kicker="Brands"
        title="Brands for agents"
        description="Public catalog of active brands. Open a brand to see teams and products you can distribute."
      />
      <StateBlock
        loading={loading}
        error={error}
        empty={brands.length === 0}
        emptyTitle="No brands available"
        emptyBody="Active brands will appear here when they are published for agents."
      >
        <div className="grid gap-4 md:grid-cols-2">
          {brands.map((brand) => (
            <Link
              key={brand.id}
              href={`/dashboard/brands/${brand.id}`}
              className="rounded-2xl border border-line bg-card p-6 hover:border-[var(--misa-blue)]"
            >
              <p className="text-xs uppercase tracking-[0.16em] text-muted">{brand.category_name}</p>
              <h2 className="mt-2 text-2xl">{brand.name}</h2>
              <p className="mt-2 line-clamp-3 text-sm text-muted">
                {brand.description || "No public description."}
              </p>
              <p className="mt-4 text-sm text-muted">
                {brand.location || "Location not listed"} · {brand.product_count} products · {brand.team_count} teams
              </p>
              {brand.membership_status === "active" ? (
                <p className="mt-3 text-sm text-success">You are on a team</p>
              ) : null}
            </Link>
          ))}
        </div>
      </StateBlock>
    </div>
  );
}
