"use client";

import { useEffect, useState } from "react";

import { PageHead, StateBlock, StatCard } from "@/components/agent/ui";
import { money } from "@/lib/agent";
import { api, endpoints, type BrandDistributionRow } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function BrandDistributionPage() {
  const { token } = useAuth();
  const [rows, setRows] = useState<BrandDistributionRow[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    api<BrandDistributionRow[]>(endpoints.brands.distribution, { token })
      .then((payload) => {
        setRows(payload);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token]);

  return (
    <div>
      <PageHead
        kicker="Distribution"
        title="Products, generated videos, and agent activity"
        description="Available videos are existing Studio exports. Counts come from recorded tracking events only."
      />
      <StateBlock
        loading={loading}
        error={error}
        empty={rows.length === 0}
        emptyTitle="No products to distribute"
      >
        <div className="space-y-6">
          {rows.map((row) => (
            <section key={row.product_id} className="rounded-2xl border border-line bg-card p-5">
              <h2 className="text-xl text-[var(--misa-navy)]">{row.product_name}</h2>
              <p className="text-sm text-muted">{row.brand_name}</p>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <StatCard label="Generated content" value={row.generated_content} />
                <StatCard label="Available videos" value={row.available_videos} />
                <StatCard label="Active agents" value={row.active_agents} />
                <StatCard label="Tracking links" value={row.tracking_links} />
                <StatCard label="Opens" value={row.opens} />
                <StatCard label="Unique opens" value={row.unique_opens ?? 0} />
                <StatCard label="Conversions" value={row.conversions} />
                <StatCard label="Commission generated" value={money(row.commission_generated)} />
              </div>
              {row.available_content.length ? (
                <ul className="mt-4 space-y-2 text-sm">
                  {row.available_content.map((item) => (
                    <li key={item.id} className="rounded-xl border border-line px-4 py-3">
                      Studio project #{item.id} · {item.status}
                      {item.export_url ? (
                        <a href={item.export_url} className="ml-2 text-gold" target="_blank" rel="noreferrer">
                          Open export
                        </a>
                      ) : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-4 text-sm text-muted">No approved or exported Studio videos for this product yet.</p>
              )}
            </section>
          ))}
        </div>
      </StateBlock>
    </div>
  );
}
