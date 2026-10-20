"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { SiteHeader } from "@/components/SiteHeader";
import { useAuth } from "@/lib/auth";
import { homePath, postLoginPath } from "@/lib/paths";

export default function LoginPage() {
  const router = useRouter();
  const { login, user, ready, workspace, actingAccount } = useAuth();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (ready && user) {
      router.replace(homePath(user, workspace, actingAccount));
    }
  }, [ready, user, workspace, actingAccount, router]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      const account = await login(identifier, password, "agent");
      router.push(postLoginPath(account));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to log in.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <SiteHeader />
      <main className="app-width grid flex-1 items-center gap-10 py-12 lg:grid-cols-2">
        <div className="auth-hero-card hidden p-10 lg:block">
          <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-primary">
            Agent access
          </p>
          <h1 className="mt-4 font-serif text-5xl leading-tight">
            Welcome back. Pick up your tracking links and earnings.
          </h1>
          <p className="mt-5 max-w-md text-muted">
            Log in with your username or email. This area is for agents who
            share tracking links and earn commissions.
          </p>
        </div>

        <form
          onSubmit={onSubmit}
          className="rounded-3xl border border-line bg-card p-8"
        >
          <h2 className="font-serif text-3xl">Log in</h2>
          <p className="mt-2 text-sm text-muted">
            Use your username or the email on your agent account.
          </p>

          {error ? (
            <p className="mt-5 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </p>
          ) : null}

          <label className="mt-6 block text-sm">
            Username or email
            <input
              required
              value={identifier}
              onChange={(event) => setIdentifier(event.target.value)}
              autoComplete="username"
              className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
            />
          </label>

          <label className="mt-4 block text-sm">
            Password
            <input
              required
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
              className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
            />
          </label>

          <button
            type="submit"
            disabled={pending}
            className="mt-7 h-12 w-full rounded-[13px] bg-gold text-sm font-medium text-white hover:bg-gold-deep disabled:opacity-60"
          >
            {pending ? "Signing in…" : "Log in"}
          </button>

          <p className="mt-5 text-center text-sm text-muted">
            New agent?{" "}
            <Link href="/register" className="text-gold hover:underline">
              Create an account
            </Link>
          </p>
          <p className="mt-2 text-center text-sm text-muted">
            Brand owner?{" "}
            <Link href="/brand/login" className="text-gold hover:underline">
              Use brand log in
            </Link>
          </p>
        </form>
      </main>
    </div>
  );
}
