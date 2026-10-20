"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { CreateTrackingLink } from "@/components/agent/CreateTrackingLink";
import { CommissionBlock, PageHead, StateBlock } from "@/components/agent/ui";
import { api, endpoints, type AgentProductDetail } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AgentProductDetailPage() {
  const params = useParams<{ id: string }>();
  const { token } = useAuth();
  const [product, setProduct] = useState<AgentProductDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token || !params.id) return;
    api<AgentProductDetail>(endpoints.agents.productDetail(Number(params.id)), { token })
      .then((payload) => {
        setProduct(payload);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token, params.id]);

  return (
    <div>
      <StateBlock loading={loading} error={error}>
        {product ? (
          <>
            <PageHead kicker={product.brand_name} title={product.name} description={product.description} />
            <div className="grid gap-8 lg:grid-cols-[1.2fr_0.8fr]">
              <div className="space-y-6">
                {product.images.length ? (
                  <div className="grid grid-cols-2 gap-3">
                    {product.images.map((image) => (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img key={image.id} src={image.url} alt="" className="h-40 w-full rounded-2xl object-cover" />
                    ))}
                  </div>
                ) : null}

                <section className="rounded-2xl border border-line bg-card p-5">
                  <h2 className="text-lg">Product information</h2>
                  <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
                    <div>
                      <dt className="text-muted">Price</dt>
                      <dd>{product.price}</dd>
                    </div>
                    <div>
                      <dt className="text-muted">Materials</dt>
                      <dd>{product.materials || "—"}</dd>
                    </div>
                    <div>
                      <dt className="text-muted">Offer</dt>
                      <dd>{product.offer || "—"}</dd>
                    </div>
                    <div>
                      <dt className="text-muted">Variants</dt>
                      <dd>{product.variants.join(", ") || "—"}</dd>
                    </div>
                  </dl>
                </section>

                <section className="rounded-2xl border border-line bg-card p-5">
                  <h2 className="text-lg">Approved marketing content</h2>
                  {product.can_share && product.approved_claims.length ? (
                    <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">
                      {product.approved_claims.map((claim) => (
                        <li key={claim}>{claim}</li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-3 text-sm text-muted">
                      {product.can_share
                        ? "No approved claims are listed for this product."
                        : "Join a team to see approved marketing content."}
                    </p>
                  )}
                </section>

                <section className="rounded-2xl border border-line bg-card p-5">
                  <h2 className="text-lg">Videos / reels</h2>
                  {product.content.length || product.demo_videos.length ? (
                    <ul className="mt-3 space-y-3 text-sm">
                      {product.content.map((item) => (
                        <li key={item.id} className="rounded-xl border border-line p-3">
                          Video #{item.id} · {item.status} · {item.duration_seconds}s
                          {item.export_url || item.preview_url ? (
                            <a
                              href={item.export_url || item.preview_url}
                              className="ml-3 text-gold"
                              target="_blank"
                              rel="noreferrer"
                            >
                              Open
                            </a>
                          ) : null}
                        </li>
                      ))}
                      {product.demo_videos.map((video) => (
                        <li key={video.id}>
                          <a href={video.url} className="text-gold" target="_blank" rel="noreferrer">
                            Demo video
                          </a>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-3 text-sm text-muted">No approved videos are available.</p>
                  )}
                </section>
              </div>

              <div className="space-y-6">
                <section className="rounded-2xl border border-line bg-card p-5">
                  <h2 className="text-lg">Commission</h2>
                  {product.commissions.length ? (
                    <div className="mt-4 space-y-4">
                      {product.commissions.map((item) => (
                        <div key={`${item.team_id}-${item.source}`}>
                          <p className="text-sm font-medium">
                            {item.team_name}
                            {item.team_specific ? " · team-specific" : ""}
                          </p>
                          <div className="mt-2">
                            <CommissionBlock gross={item.gross} fee={item.platform_fee} net={item.net} />
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-3 text-sm text-muted">
                      {product.can_share
                        ? "No commission rule is configured for your teams."
                        : "Join a team to see commission information."}
                    </p>
                  )}
                </section>
                {token ? <CreateTrackingLink product={product} token={token} /> : null}
              </div>
            </div>
          </>
        ) : null}
      </StateBlock>
    </div>
  );
}
