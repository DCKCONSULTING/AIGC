"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  Field,
  PageHead,
  StateBlock,
  inputClass,
  primaryButtonClass,
} from "@/components/agent/ui";
import { api, endpoints, type BrandCampaign, type BrandTeam, type Product, type VideoProject } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const emptyForm = {
  name: "",
  product: "",
  team: "",
  content: "",
  start_at: "",
  end_at: "",
  commission_type: "fixed",
  commission_value: "",
  status: "draft",
};

export default function BrandCampaignsPage() {
  const { token } = useAuth();
  const [campaigns, setCampaigns] = useState<BrandCampaign[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [teams, setTeams] = useState<BrandTeam[]>([]);
  const [videos, setVideos] = useState<VideoProject[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);

  const load = useCallback(() => {
    if (!token) return;
    Promise.all([
      api<BrandCampaign[]>(endpoints.brands.campaigns, { token }),
      api<Product[]>(endpoints.brands.products, { token }),
      api<BrandTeam[]>(endpoints.brands.teams, { token }),
      api<VideoProject[]>(endpoints.ai.videos, { token }),
    ])
      .then(([nextCampaigns, nextProducts, nextTeams, nextVideos]) => {
        setCampaigns(nextCampaigns);
        setProducts(nextProducts);
        setTeams(nextTeams);
        setVideos(nextVideos);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const availableVideos = videos.filter(
    (video) =>
      (!form.product || String(video.product) === form.product) &&
      (video.status === "approved" || video.status === "exported"),
  );

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setPending(true);
    setError("");
    try {
      await api(endpoints.brands.campaigns, {
        method: "POST",
        token,
        body: JSON.stringify({
          name: form.name,
          product: form.product ? Number(form.product) : null,
          team: form.team ? Number(form.team) : null,
          content: form.content ? Number(form.content) : null,
          start_at: form.start_at || null,
          end_at: form.end_at || null,
          commission_type: form.commission_value ? form.commission_type : "",
          commission_value: form.commission_value || null,
          status: form.status,
        }),
      });
      setForm(emptyForm);
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <PageHead
        kicker="Campaigns"
        title="Assign product, content, and team"
        description="Campaigns group distribution. Content is a reference to an existing Studio export, not a copy."
      />
      <form onSubmit={onCreate} className="mb-8 grid gap-3 rounded-2xl border border-line bg-card p-5 md:grid-cols-2">
        <Field label="Name">
          <input
            className={inputClass}
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
            required
          />
        </Field>
        <Field label="Status">
          <select
            className={inputClass}
            value={form.status}
            onChange={(event) => setForm({ ...form, status: event.target.value })}
          >
            <option value="draft">Draft</option>
            <option value="active">Active</option>
            <option value="paused">Paused</option>
            <option value="ended">Ended</option>
          </select>
        </Field>
        <Field label="Product">
          <select
            className={inputClass}
            value={form.product}
            onChange={(event) => setForm({ ...form, product: event.target.value, content: "" })}
          >
            <option value="">None</option>
            {products.map((product) => (
              <option key={product.id} value={product.id}>
                {product.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Team">
          <select
            className={inputClass}
            value={form.team}
            onChange={(event) => setForm({ ...form, team: event.target.value })}
          >
            <option value="">None</option>
            {teams.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Studio content">
          <select
            className={inputClass}
            value={form.content}
            onChange={(event) => setForm({ ...form, content: event.target.value })}
          >
            <option value="">None</option>
            {availableVideos.map((video) => (
              <option key={video.id} value={video.id}>
                #{video.id} · {video.status} · {video.product_name || "product"}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Commission">
          <div className="grid grid-cols-[140px_1fr] gap-2">
            <select
              className={inputClass}
              value={form.commission_type}
              onChange={(event) => setForm({ ...form, commission_type: event.target.value })}
            >
              <option value="fixed">Fixed $</option>
              <option value="percent">Percent</option>
            </select>
            <input
              className={inputClass}
              value={form.commission_value}
              onChange={(event) => setForm({ ...form, commission_value: event.target.value })}
              placeholder="Optional"
            />
          </div>
        </Field>
        <Field label="Start">
          <input
            type="datetime-local"
            className={inputClass}
            value={form.start_at}
            onChange={(event) => setForm({ ...form, start_at: event.target.value })}
          />
        </Field>
        <Field label="End">
          <input
            type="datetime-local"
            className={inputClass}
            value={form.end_at}
            onChange={(event) => setForm({ ...form, end_at: event.target.value })}
          />
        </Field>
        <div className="md:col-span-2">
          <button type="submit" className={primaryButtonClass} disabled={pending}>
            {pending ? "Saving…" : "Create campaign"}
          </button>
        </div>
      </form>
      <StateBlock
        loading={loading}
        error={error}
        empty={campaigns.length === 0}
        emptyTitle="No campaigns"
        emptyBody="Create a campaign to assign a product, team, dates, and optional Studio export."
      >
        <div className="space-y-4">
          {campaigns.map((campaign) => (
            <Link
              key={campaign.id}
              href={`/brand/campaigns/${campaign.id}`}
              className="block rounded-2xl border border-line bg-card p-5 hover:border-gold"
            >
              <div className="flex flex-wrap justify-between gap-3">
                <div>
                  <h2 className="text-xl">{campaign.name}</h2>
                  <p className="mt-1 text-sm text-muted">
                    {campaign.product_name || "No product"} · {campaign.team_name || "No team"}
                    {campaign.content_id ? ` · Video #${campaign.content_id}` : ""}
                  </p>
                </div>
                <span className="text-xs uppercase tracking-[0.14em]">{campaign.status}</span>
              </div>
            </Link>
          ))}
        </div>
      </StateBlock>
    </div>
  );
}
