"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";

import {
  Field,
  PageHead,
  StateBlock,
  StatCard,
  inputClass,
  primaryButtonClass,
  secondaryButtonClass,
} from "@/components/agent/ui";
import { CommissionLayers } from "@/components/brand/CommissionLayers";
import { money } from "@/lib/agent";
import {
  api,
  endpoints,
  type BrandCampaign,
  type BrandCommissionPreview,
  type BrandTeam,
  type Product,
  type VideoProject,
} from "@/lib/api";
import { previewQuery } from "@/lib/brand";
import { useAuth } from "@/lib/auth";

function toLocal(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toISOString().slice(0, 16);
}

export default function BrandCampaignDetailPage() {
  const params = useParams<{ id: string }>();
  const { token } = useAuth();
  const [campaign, setCampaign] = useState<BrandCampaign | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [teams, setTeams] = useState<BrandTeam[]>([]);
  const [videos, setVideos] = useState<VideoProject[]>([]);
  const [preview, setPreview] = useState<BrandCommissionPreview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [form, setForm] = useState({
    name: "",
    product: "",
    team: "",
    content: "",
    start_at: "",
    end_at: "",
    commission_type: "fixed",
    commission_value: "",
    status: "draft",
  });

  const load = useCallback(() => {
    if (!token || !params.id) return;
    api<BrandCampaign>(endpoints.brands.campaignDetail(Number(params.id)), { token })
      .then((payload) => {
        setCampaign(payload);
        setForm({
          name: payload.name,
          product: payload.product_id ? String(payload.product_id) : "",
          team: payload.team_id ? String(payload.team_id) : "",
          content: payload.content_id ? String(payload.content_id) : "",
          start_at: toLocal(payload.start_at),
          end_at: toLocal(payload.end_at),
          commission_type: payload.commission_type || "fixed",
          commission_value: payload.commission_value || "",
          status: payload.status,
        });
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token, params.id]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      api<Product[]>(endpoints.brands.products, { token }),
      api<BrandTeam[]>(endpoints.brands.teams, { token }),
      api<VideoProject[]>(endpoints.ai.videos, { token }),
    ]).then(([nextProducts, nextTeams, nextVideos]) => {
      setProducts(nextProducts);
      setTeams(nextTeams);
      setVideos(nextVideos);
    });
  }, [token]);

  useEffect(() => {
    if (!token || !form.product) {
      setPreview(null);
      return;
    }
    api<BrandCommissionPreview>(
      previewQuery({
        product: form.product,
        team: form.team,
        campaign: params.id,
      }),
      { token },
    )
      .then(setPreview)
      .catch(() => setPreview(null));
  }, [token, form.product, form.team, params.id]);

  async function onSave(event: FormEvent) {
    event.preventDefault();
    if (!token || !campaign) return;
    setPending(true);
    try {
      await api(endpoints.brands.campaignDetail(campaign.id), {
        method: "PATCH",
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
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  async function toggleActive() {
    if (!token || !campaign) return;
    const next = campaign.status === "active" ? "paused" : "active";
    await api(endpoints.brands.campaignDetail(campaign.id), {
      method: "PATCH",
      token,
      body: JSON.stringify({ status: next }),
    });
    load();
  }

  const availableVideos = videos.filter(
    (video) =>
      (!form.product || String(video.product) === form.product) &&
      (video.status === "approved" || video.status === "exported"),
  );
  const performance = campaign?.performance;

  return (
    <div>
      <StateBlock loading={loading} error={error}>
        {campaign ? (
          <>
            <PageHead kicker="Campaign" title={campaign.name} />
            {performance ? (
              <div className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                <StatCard label="Links" value={performance.links} />
                <StatCard label="Opens" value={performance.opens} />
                <StatCard label="Unique opens" value={performance.unique_opens ?? 0} />
                <StatCard label="Conversions" value={performance.conversions} />
                <StatCard label="Gross commissions" value={money(performance.gross_commissions)} />
                <StatCard label="Platform fees" value={money(performance.platform_fees)} />
                <StatCard label="Agent payouts" value={money(performance.agent_payouts)} />
              </div>
            ) : null}
            <CommissionLayers preview={preview} />
            <form onSubmit={onSave} className="mt-8 grid gap-3 rounded-2xl border border-line bg-card p-5 md:grid-cols-2">
              <Field label="Name">
                <input
                  className={inputClass}
                  value={form.name}
                  onChange={(event) => setForm({ ...form, name: event.target.value })}
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
                  onChange={(event) => setForm({ ...form, product: event.target.value })}
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
                      #{video.id} · {video.status}
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
              <div className="flex flex-wrap gap-3 md:col-span-2">
                <button type="submit" className={primaryButtonClass} disabled={pending}>
                  Save
                </button>
                <button type="button" className={secondaryButtonClass} onClick={toggleActive}>
                  {campaign.status === "active" ? "Deactivate" : "Activate"}
                </button>
              </div>
            </form>
            {campaign.content_ref ? (
              <p className="mt-4 text-sm text-muted">
                Assigned Studio project #{campaign.content_ref.id} ({campaign.content_ref.status}).
              </p>
            ) : null}
            <Link href="/brand/campaigns" className="mt-6 inline-block text-sm text-gold">
              Back to campaigns
            </Link>
          </>
        ) : null}
      </StateBlock>
    </div>
  );
}
