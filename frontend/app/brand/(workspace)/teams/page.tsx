"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { PageHead, StateBlock, inputClass, primaryButtonClass } from "@/components/agent/ui";
import { api, endpoints, type Brand, type BrandTeam } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function BrandTeamsPage() {
  const { token, actingAccount } = useAuth();
  const [teams, setTeams] = useState<BrandTeam[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [brandId, setBrandId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);

  const load = useCallback(() => {
    if (!token) return;
    Promise.all([
      api<BrandTeam[]>(endpoints.brands.teams, { token }),
      api<Brand[]>(endpoints.brands.list, { token }),
    ])
      .then(([rows, nextBrands]) => {
        setTeams(rows);
        setBrands(nextBrands);
        setBrandId((current) => {
          if (current && nextBrands.some((brand) => String(brand.id) === current)) return current;
          const acting = actingAccount?.brandId ? String(actingAccount.brandId) : "";
          const match = nextBrands.find((brand) => String(brand.id) === acting);
          return String((match || nextBrands[0])?.id || "");
        });
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token, actingAccount?.brandId]);

  useEffect(() => {
    load();
  }, [load]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    if (!brandId) {
      setFormError("Choose a brand for this team.");
      return;
    }
    setPending(true);
    setFormError("");
    try {
      await api(endpoints.brands.teams, {
        method: "POST",
        token,
        body: JSON.stringify({ name, description, brand: Number(brandId) }),
      });
      setName("");
      setDescription("");
      load();
    } catch (err) {
      setFormError((err as Error).message);
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <PageHead
        kicker="Agent Teams"
        title="Teams you manage"
        description="Create teams, invite agents, and review membership. Each brand can have more than one team."
      />
      <form onSubmit={onCreate} className="mb-8 grid gap-3 rounded-2xl border border-line bg-card p-5 md:grid-cols-2">
        <label className="block text-sm md:col-span-2">
          <span className="mb-1 block text-muted">Brand</span>
          <select
            className={inputClass}
            value={brandId}
            onChange={(event) => setBrandId(event.target.value)}
            required
          >
            {brands.length === 0 ? <option value="">Create a brand first</option> : null}
            {brands.map((brand) => (
              <option key={brand.id} value={brand.id}>
                {brand.name}
              </option>
            ))}
          </select>
        </label>
        <input
          className={inputClass}
          placeholder="Team name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
        />
        <input
          className={inputClass}
          placeholder="Description (optional)"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
        />
        {formError ? <p className="text-sm text-error md:col-span-2">{formError}</p> : null}
        <button type="submit" className={`${primaryButtonClass} md:col-span-2 w-fit`} disabled={pending || !brandId}>
          {pending ? "Creating…" : "Create team"}
        </button>
      </form>
      <StateBlock
        loading={loading}
        error={error}
        empty={teams.length === 0}
        emptyTitle="No teams yet"
        emptyBody="Create a team to invite agents and review join requests."
      >
        <div className="space-y-4">
          {teams.map((team) => (
            <Link
              key={team.id}
              href={`/brand/teams/${team.id}`}
              className="block rounded-2xl border border-line bg-card p-5 hover:border-gold"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-xl text-[var(--misa-navy)]">{team.name}</h2>
                  <p className="mt-1 text-sm text-muted">{team.brand_name}</p>
                  {team.description ? <p className="mt-1 text-sm text-muted">{team.description}</p> : null}
                </div>
                <span className="rounded-full border border-line px-3 py-1 text-xs uppercase tracking-[0.14em]">
                  {team.status}
                </span>
              </div>
              <p className="mt-3 text-sm text-muted">
                {team.member_count} members · {team.pending_requests} join requests · {team.pending_invites}{" "}
                invitations
              </p>
            </Link>
          ))}
        </div>
      </StateBlock>
    </div>
  );
}
