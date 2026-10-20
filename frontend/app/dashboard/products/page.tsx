"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { PageHead, StateBlock } from "@/components/agent/ui";
import { api, endpoints, type AgentProductCard } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AgentProductsPage() {
  const { token } = useAuth();
  const [products, setProducts] = useState<AgentProductCard[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    api<AgentProductCard[]>(endpoints.agents.products, { token })
      .then((rows) => {
        setProducts(rows);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token]);

  return (
    <div>
      <PageHead
        kicker="Products"
        title="Products available to you"
        description="These products belong to brands where you are an active team member."
      />
      <StateBlock
        loading={loading}
        error={error}
        empty={products.length === 0}
        emptyTitle="No products available"
        emptyBody="Join a brand team to see products you can share."
      >
        <div className="grid gap-4 md:grid-cols-2">
          {products.map((product) => (
            <Link
              key={product.id}
              href={`/dashboard/products/${product.id}`}
              className="overflow-hidden rounded-2xl border border-line bg-card hover:border-[var(--misa-blue)]"
            >
              {product.images[0]?.url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={product.images[0].url} alt="" className="h-40 w-full object-cover" />
              ) : null}
              <div className="p-5">
                <p className="text-xs uppercase tracking-[0.16em] text-muted">{product.brand_name}</p>
                <h2 className="mt-2 text-xl">{product.name}</h2>
                <p className="mt-2 line-clamp-3 text-sm text-muted">
                  {product.description || "No public description."}
                </p>
              </div>
            </Link>
          ))}
        </div>
      </StateBlock>
    </div>
  );
}
