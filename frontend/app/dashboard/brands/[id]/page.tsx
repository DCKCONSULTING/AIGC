"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { TeamActions } from "@/components/agent/TeamActions";
import { PageHead, StateBlock, primaryButtonClass } from "@/components/agent/ui";
import { api, endpoints, type AgentBrandDetail } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AgentBrandDetailPage() {
  const params = useParams<{ id: string }>();
  const { token } = useAuth();
  const [data, setData] = useState<AgentBrandDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    if (!token || !params.id) return;
    api<AgentBrandDetail>(endpoints.agents.brandDetail(Number(params.id)), { token })
      .then((payload) => {
        setData(payload);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token, params.id]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <StateBlock loading={loading} error={error}>
        {data ? (
          <>
            <PageHead
              kicker={data.brand.category_name}
              title={data.brand.name}
              description={data.brand.description || "No public description."}
            />
            <p className="mb-6 text-sm text-muted">
              {data.brand.location || "Location not listed"}
              {data.brand.website ? ` · ${data.brand.website}` : ""}
            </p>
            {token ? <BrandJoin data={data} token={token} onChange={load} /> : null}

            <h2 className="text-xl">Teams</h2>
            <div className="mt-4">
              <StateBlock
                loading={false}
                error=""
                empty={data.teams.length === 0}
                emptyTitle="No teams yet"
                emptyBody="Request to join above. The brand owner approves you before you can represent this brand."
              >
                <div className="space-y-4">
                  {data.teams.map((team) => (
                    <div key={team.id} className="rounded-2xl border border-line bg-card p-5">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <Link href={`/dashboard/teams/${team.id}`} className="text-lg hover:text-gold">
                            {team.name}
                          </Link>
                          <p className="mt-1 text-sm text-muted">{team.description || "No description."}</p>
                        </div>
                        {token ? <TeamActions team={team} token={token} onChange={load} /> : null}
                      </div>
                    </div>
                  ))}
                </div>
              </StateBlock>
            </div>

            <h2 className="mt-10 text-xl">Products</h2>
            <div className="mt-4">
              <StateBlock
                loading={false}
                error=""
                empty={data.products.length === 0}
                emptyTitle="No products"
                emptyBody="This brand has not listed products for agents."
              >
                <div className="grid gap-4 md:grid-cols-2">
                  {data.products.map((product) => (
                    <Link
                      key={product.id}
                      href={`/dashboard/products/${product.id}`}
                      className="rounded-2xl border border-line bg-card p-5 hover:border-[var(--misa-blue)]"
                    >
                      <h3 className="text-lg">{product.name}</h3>
                      <p className="mt-2 line-clamp-3 text-sm text-muted">
                        {product.description || "No public description."}
                      </p>
                    </Link>
                  ))}
                </div>
              </StateBlock>
            </div>
          </>
        ) : null}
      </StateBlock>
    </div>
  );
}

function BrandJoin({
  data,
  token,
  onChange,
}: {
  data: AgentBrandDetail;
  token: string;
  onChange: () => void;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [teamId, setTeamId] = useState("");
  const member =
    data.brand.membership_status === "active" ||
    data.teams.some((team) => team.membership_status === "active");
  const waiting = data.teams.find((team) => team.join_request_status === "pending");
  const choices = data.teams.filter((team) => team.status === "active" && team.can_join);

  async function requestJoin() {
    if (choices.length > 1 && !teamId) {
      setError("Choose a team to join.");
      return;
    }
    setPending(true);
    setError("");
    try {
      await api(endpoints.agents.brandJoin(data.brand.id), {
        method: "POST",
        token,
        body: JSON.stringify(choices.length > 1 ? { team: Number(teamId) } : {}),
      });
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the request.");
    } finally {
      setPending(false);
    }
  }

  if (member) {
    return <p className="mb-8 text-sm text-muted">You are a member of this brand.</p>;
  }

  if (waiting) {
    return (
      <p className="mb-8 rounded-2xl border border-line bg-card px-5 py-4 text-sm text-muted">
        Request sent for {waiting.name}. The brand owner still needs to approve it before you can represent{" "}
        {data.brand.name}.
      </p>
    );
  }

  return (
    <div className="mb-8 rounded-2xl border border-line bg-card p-5">
      <p className="text-sm text-muted">
        Ask to represent {data.brand.name}. The brand owner approves this request before you become a member.
      </p>
      {choices.length > 1 ? (
        <label className="mt-4 block text-sm">
          <span className="mb-1 block text-muted">Team</span>
          <select
            className="h-11 w-full max-w-sm rounded-xl border border-line bg-white px-3 text-sm"
            value={teamId}
            onChange={(event) => setTeamId(event.target.value)}
          >
            <option value="">Choose a team</option>
            {choices.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {error ? <p className="mt-3 text-sm text-red-700">{error}</p> : null}
      <button type="button" disabled={pending} className={`${primaryButtonClass} mt-4`} onClick={() => void requestJoin()}>
        {pending ? "Sending…" : "Request to join"}
      </button>
    </div>
  );
}
