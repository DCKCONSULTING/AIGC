"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

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
  type BrandAgentRow,
  type BrandCommissionPreview,
  type BrandCommissionRule,
  type BrandTeam,
  type Product,
} from "@/lib/api";
import { previewQuery } from "@/lib/brand";
import { useAuth } from "@/lib/auth";

export default function BrandCommissionsPage() {
  const { token } = useAuth();
  const [products, setProducts] = useState<Product[]>([]);
  const [teams, setTeams] = useState<BrandTeam[]>([]);
  const [agents, setAgents] = useState<BrandAgentRow[]>([]);
  const [rules, setRules] = useState<BrandCommissionRule[]>([]);
  const [preview, setPreview] = useState<BrandCommissionPreview | null>(null);
  const [productId, setProductId] = useState("");
  const [teamId, setTeamId] = useState("");
  const [agentId, setAgentId] = useState("");
  const [defaultAmount, setDefaultAmount] = useState("");
  const [teamAmount, setTeamAmount] = useState("");
  const [agentAmount, setAgentAmount] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);

  const loadLists = useCallback(() => {
    if (!token) return;
    Promise.all([
      api<Product[]>(endpoints.brands.products, { token }),
      api<BrandTeam[]>(endpoints.brands.teams, { token }),
      api<BrandAgentRow[]>(endpoints.brands.agents, { token }),
      api<BrandCommissionRule[]>(endpoints.brands.commissionRules, { token }),
    ])
      .then(([nextProducts, nextTeams, nextAgents, nextRules]) => {
        setProducts(nextProducts);
        setTeams(nextTeams);
        setAgents(nextAgents);
        setRules(nextRules);
        if (!productId && nextProducts[0]) setProductId(String(nextProducts[0].id));
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token, productId]);

  useEffect(() => {
    loadLists();
  }, [loadLists]);

  const selectedProduct = products.find((product) => String(product.id) === productId);

  useEffect(() => {
    if (selectedProduct) setDefaultAmount(selectedProduct.commission_amount || selectedProduct.commission || "");
  }, [selectedProduct]);

  const loadPreview = useCallback(() => {
    if (!token || !productId) {
      setPreview(null);
      return;
    }
    api<BrandCommissionPreview>(
      previewQuery({ product: productId, team: teamId, agent: agentId }),
      { token },
    )
      .then((payload) => {
        setPreview(payload);
        setTeamAmount(payload.layers.team.configured ? payload.layers.team.rate_value || "" : "");
        setAgentAmount(payload.layers.agent.configured ? payload.layers.agent.rate_value || "" : "");
      })
      .catch(() => setPreview(null));
  }, [token, productId, teamId, agentId]);

  useEffect(() => {
    loadPreview();
  }, [loadPreview]);

  async function saveDefault(event: FormEvent) {
    event.preventDefault();
    if (!token || !productId) return;
    setPending(true);
    try {
      await api(endpoints.brands.productCommission(Number(productId)), {
        method: "PATCH",
        token,
        body: JSON.stringify({ commission_amount: defaultAmount || "0" }),
      });
      loadLists();
      loadPreview();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  async function saveTeam(event: FormEvent) {
    event.preventDefault();
    if (!token || !teamId) return;
    setPending(true);
    try {
      await api(endpoints.brands.commissionRules, {
        method: "POST",
        token,
        body: JSON.stringify({
          scope: "team",
          team: Number(teamId),
          rate_type: "fixed",
          rate_value: teamAmount,
        }),
      });
      loadLists();
      loadPreview();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  async function saveAgent(event: FormEvent) {
    event.preventDefault();
    if (!token || !agentId) return;
    setPending(true);
    try {
      await api(endpoints.brands.commissionRules, {
        method: "POST",
        token,
        body: JSON.stringify({
          scope: "agent",
          agent: Number(agentId),
          team: teamId ? Number(teamId) : undefined,
          product: productId ? Number(productId) : undefined,
          rate_type: "fixed",
          rate_value: agentAmount,
        }),
      });
      loadLists();
      loadPreview();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <PageHead
        kicker="Commissions"
        title="Default, team, and agent rules"
        description="Changing a rule does not rewrite past commission transactions. The highlighted layer is the one that would apply now."
      />
      <StateBlock loading={loading} error={error}>
        <div className="mb-6 grid gap-3 md:grid-cols-3">
          <Field label="Product">
            <select className={inputClass} value={productId} onChange={(event) => setProductId(event.target.value)}>
              {products.map((product) => (
                <option key={product.id} value={product.id}>
                  {product.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Team">
            <select className={inputClass} value={teamId} onChange={(event) => setTeamId(event.target.value)}>
              <option value="">None</option>
              {teams.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Agent">
            <select className={inputClass} value={agentId} onChange={(event) => setAgentId(event.target.value)}>
              <option value="">None</option>
              {agents.map((agent) => (
                <option key={`${agent.id}-${agent.agent_id}`} value={agent.agent_id}>
                  {agent.agent_name}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <CommissionLayers preview={preview} />

        <div className="mt-8 grid gap-4 md:grid-cols-3">
          <form onSubmit={saveDefault} className="rounded-2xl border border-line bg-card p-5">
            <p className="text-sm text-muted">Default product commission</p>
            <input
              className={`${inputClass} mt-3`}
              value={defaultAmount}
              onChange={(event) => setDefaultAmount(event.target.value)}
              placeholder="1.00"
            />
            <button type="submit" className={`${primaryButtonClass} mt-4`} disabled={pending || !productId}>
              Save default
            </button>
          </form>
          <form onSubmit={saveTeam} className="rounded-2xl border border-line bg-card p-5">
            <p className="text-sm text-muted">Team commission</p>
            <input
              className={`${inputClass} mt-3`}
              value={teamAmount}
              onChange={(event) => setTeamAmount(event.target.value)}
              placeholder="1.10"
            />
            <button type="submit" className={`${primaryButtonClass} mt-4`} disabled={pending || !teamId}>
              Save team rule
            </button>
          </form>
          <form onSubmit={saveAgent} className="rounded-2xl border border-line bg-card p-5">
            <p className="text-sm text-muted">Agent commission</p>
            <input
              className={`${inputClass} mt-3`}
              value={agentAmount}
              onChange={(event) => setAgentAmount(event.target.value)}
              placeholder="1.25"
            />
            <button type="submit" className={`${primaryButtonClass} mt-4`} disabled={pending || !agentId}>
              Save agent rule
            </button>
          </form>
        </div>

        <section className="mt-10">
          <h2 className="text-xl">Saved rules</h2>
          <p className="mt-2 text-sm text-muted">
            Historical commission rows are snapshots. Deactivating a rule only changes future conversions.
          </p>
          <div className="mt-4">
            <StateBlock loading={false} error="" empty={rules.length === 0} emptyTitle="No extra rules yet">
              <ul className="divide-y divide-line rounded-2xl border border-line bg-card">
                {rules.map((rule) => (
                  <li key={rule.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-sm">
                    <span>
                      {rule.scope} · {rule.rate_type} {money(rule.rate_value)} ·{" "}
                      {rule.product_name || rule.team_name || rule.agent_name || "brand"}
                      {rule.is_active ? "" : " (inactive)"}
                    </span>
                    {rule.is_active ? (
                      <button
                        type="button"
                        className={secondaryButtonClass}
                        onClick={() =>
                          token &&
                          api(endpoints.brands.commissionRuleDetail(rule.id), { method: "DELETE", token }).then(
                            loadLists,
                          )
                        }
                      >
                        Deactivate
                      </button>
                    ) : null}
                  </li>
                ))}
              </ul>
            </StateBlock>
          </div>
        </section>
      </StateBlock>
    </div>
  );
}
