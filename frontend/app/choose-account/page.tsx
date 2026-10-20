"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { SiteHeader } from "@/components/SiteHeader";
import {
  api,
  endpoints,
  type Role,
  type WorkspaceAgent,
  type WorkspaceBrand,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { homePath, loginPath } from "@/lib/paths";

export default function ChooseAccountPage() {
  const router = useRouter();
  const { user, token, ready, workspace, actingAccount, chooseAccount } = useAuth();
  const [kind, setKind] = useState<Role | null>(null);
  const [brands, setBrands] = useState<WorkspaceBrand[]>([]);
  const [agents, setAgents] = useState<WorkspaceAgent[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!ready) return;
    if (!user) {
      router.replace(loginPath("agent"));
      return;
    }
    if (!user.is_superuser) {
      router.replace(homePath(user, workspace, actingAccount));
    }
  }, [ready, user, workspace, actingAccount, router]);

  useEffect(() => {
    if (!token || !kind) return;
    setError("");
    setPending(true);
    const path =
      kind === "producer" ? endpoints.auth.workspaces.brands : endpoints.auth.workspaces.agents;
    api<WorkspaceBrand[] | WorkspaceAgent[]>(path, { token })
      .then((rows) => {
        if (kind === "producer") setBrands(rows as WorkspaceBrand[]);
        else setAgents(rows as WorkspaceAgent[]);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Unable to load accounts.");
      })
      .finally(() => setPending(false));
  }, [token, kind]);

  const visibleBrands = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return brands;
    return brands.filter((item) =>
      `${item.name} ${item.owner_name} ${item.location} ${item.category_name}`.toLowerCase().includes(needle),
    );
  }, [brands, query]);

  const visibleAgents = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return agents;
    return agents.filter((item) =>
      `${item.name} ${item.username} ${item.email} ${item.location}`.toLowerCase().includes(needle),
    );
  }, [agents, query]);

  if (!ready || !user?.is_superuser) {
    return (
      <div className="flex min-h-full flex-1 items-center justify-center text-muted">
        Loading…
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <SiteHeader />
      <main className="app-width flex flex-1 flex-col justify-center py-14">
        <p className="text-xs uppercase tracking-[0.22em] text-gold">
          Choose account
        </p>
        {!kind ? (
          <>
            <h1 className="mt-4 font-serif text-5xl">How do you want to continue?</h1>
            <p className="mt-4 max-w-xl text-muted">
              Pick brand or agent, then choose the company or person to open.
            </p>
            <div className="mt-10 grid gap-4 md:grid-cols-2">
              <button
                type="button"
                onClick={() => {
                  setKind("producer");
                  setQuery("");
                }}
                className="rounded-3xl border border-line bg-card p-8 text-left hover:border-gold hover:bg-gold/10"
              >
                <p className="text-xs uppercase tracking-[0.16em] text-muted">Brand</p>
                <p className="mt-3 font-serif text-3xl">Brand account</p>
                <p className="mt-3 text-sm text-muted">
                  Then choose a company dashboard.
                </p>
              </button>
              <button
                type="button"
                onClick={() => {
                  setKind("agent");
                  setQuery("");
                }}
                className="rounded-3xl border border-line bg-card p-8 text-left hover:border-gold hover:bg-gold/10"
              >
                <p className="text-xs uppercase tracking-[0.16em] text-muted">Agent</p>
                <p className="mt-3 font-serif text-3xl">Agent account</p>
                <p className="mt-3 text-sm text-muted">
                  Then choose which agent to open.
                </p>
              </button>
            </div>
          </>
        ) : (
          <>
            <h1 className="mt-4 font-serif text-5xl">
              {kind === "producer" ? "Choose a company" : "Choose an agent"}
            </h1>
            <p className="mt-4 max-w-xl text-muted">
              {kind === "producer"
                ? "Open the dashboard for that company only."
                : "Open the dashboard for that agent only."}
            </p>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={kind === "producer" ? "Search companies" : "Search agents"}
              className="mt-8 h-12 w-full rounded-xl border border-line bg-card px-4 outline-none focus:border-gold"
            />
            {error ? (
              <p className="mt-5 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </p>
            ) : null}
            <div className="mt-6 grid gap-3">
              {pending ? <p className="text-sm text-muted">Loading accounts…</p> : null}
              {kind === "producer"
                ? visibleBrands.map((brand) => (
                    <button
                      key={brand.id}
                      type="button"
                      onClick={() => {
                        const account = {
                          type: "producer" as const,
                          userId: brand.owner_id,
                          brandId: brand.id,
                          name: brand.name,
                          subtitle: brand.owner_name,
                          email: brand.owner_email,
                          username: brand.owner_username,
                          location: brand.location,
                        };
                        chooseAccount(account);
                        router.push(homePath(user, account.type, account));
                      }}
                      className="rounded-2xl border border-line bg-card px-5 py-4 text-left hover:border-gold hover:bg-gold/10"
                    >
                      <p className="font-medium">{brand.name}</p>
                      <p className="mt-1 text-sm text-muted">
                        {[brand.owner_name, brand.category_name, brand.location]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    </button>
                  ))
                : visibleAgents.map((agent) => (
                    <button
                      key={agent.id}
                      type="button"
                      onClick={() => {
                        const account = {
                          type: "agent" as const,
                          userId: agent.id,
                          name: agent.name,
                          subtitle: agent.username,
                          email: agent.email,
                          username: agent.username,
                          mobile: agent.mobile,
                          location: agent.location,
                        };
                        chooseAccount(account);
                        router.push(homePath(user, account.type, account));
                      }}
                      className="rounded-2xl border border-line bg-card px-5 py-4 text-left hover:border-gold hover:bg-gold/10"
                    >
                      <p className="font-medium">{agent.name}</p>
                      <p className="mt-1 text-sm text-muted">
                        {agent.username}
                        {agent.location ? ` · ${agent.location}` : ""}
                      </p>
                    </button>
                  ))}
              {!pending && kind === "producer" && !visibleBrands.length ? (
                <p className="text-sm text-muted">No companies yet.</p>
              ) : null}
              {!pending && kind === "agent" && !visibleAgents.length ? (
                <p className="text-sm text-muted">No agent accounts yet.</p>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => {
                setKind(null);
                setQuery("");
                setError("");
              }}
              className="mt-8 h-12 w-fit rounded-full border border-line px-6 text-sm hover:bg-black/5"
            >
              Back
            </button>
          </>
        )}
      </main>
    </div>
  );
}
