"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { SiteHeader } from "@/components/SiteHeader";
import { useAuth } from "@/lib/auth";
import { homePath } from "@/lib/paths";

const fields = [
  { key: "name", label: "Full name", autoComplete: "name", type: "text" },
  { key: "username", label: "Username", autoComplete: "username", type: "text" },
  { key: "email", label: "Email", autoComplete: "email", type: "email" },
  { key: "mobile", label: "Mobile number", autoComplete: "tel", type: "tel" },
  { key: "location", label: "Location", autoComplete: "address-level2", type: "text" },
] as const;

type FormState = {
  name: string;
  username: string;
  email: string;
  mobile: string;
  location: string;
  password: string;
  password_confirm: string;
};

const emptyForm: FormState = {
  name: "",
  username: "",
  email: "",
  mobile: "",
  location: "",
  password: "",
  password_confirm: "",
};

export default function RegisterPage() {
  const router = useRouter();
  const { register, user, ready, workspace, actingAccount } = useAuth();
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (ready && user) {
      router.replace(homePath(user, workspace, actingAccount));
    }
  }, [ready, user, workspace, actingAccount, router]);

  function update(key: keyof FormState, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      await register(form);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create account.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex min-h-full flex-1 flex-col">
      <SiteHeader />
      <main className="app-width grid flex-1 items-start gap-10 py-12 lg:grid-cols-2">
        <div className="auth-hero-card p-8 lg:sticky lg:top-24">
          <p className="text-xs font-extrabold uppercase tracking-[0.16em] text-primary">
            Agent registration
          </p>
          <h1 className="mt-4 font-serif text-5xl leading-tight">
            Join MISA and start earning from product tracking links.
          </h1>
          <p className="mt-5 max-w-md text-muted">
            We collect your name, email, mobile number, and location so brands
            can find and hire the right agents.
          </p>
        </div>

        <form
          onSubmit={onSubmit}
          className="rounded-3xl border border-line bg-card p-8"
        >
          <h2 className="font-serif text-3xl">Create agent account</h2>

          {error ? (
            <p className="mt-5 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </p>
          ) : null}

          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {fields.map((field) => (
              <label
                key={field.key}
                className={`block text-sm ${field.key === "location" ? "sm:col-span-2" : ""}`}
              >
                {field.label}
                <input
                  required
                  type={field.type}
                  autoComplete={field.autoComplete}
                  value={form[field.key]}
                  onChange={(event) => update(field.key, event.target.value)}
                  placeholder={
                    field.key === "location" ? "City, country" : undefined
                  }
                  className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
            ))}

            <label className="block text-sm">
              Password
              <input
                required
                minLength={8}
                type="password"
                autoComplete="new-password"
                value={form.password}
                onChange={(event) => update("password", event.target.value)}
                className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              />
            </label>

            <label className="block text-sm">
              Confirm password
              <input
                required
                minLength={8}
                type="password"
                autoComplete="new-password"
                value={form.password_confirm}
                onChange={(event) =>
                  update("password_confirm", event.target.value)
                }
                className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              />
            </label>
          </div>

          <button
            type="submit"
            disabled={pending}
            className="mt-7 h-12 w-full rounded-[13px] bg-gold text-sm font-medium text-white hover:bg-gold-deep disabled:opacity-60"
          >
            {pending ? "Creating account…" : "Create agent account"}
          </button>

          <p className="mt-5 text-center text-sm text-muted">
            Already registered?{" "}
            <Link href="/login" className="text-gold hover:underline">
              Log in
            </Link>
          </p>
          <p className="mt-2 text-center text-sm text-muted">
            Brand owner?{" "}
            <Link href="/brand/register" className="text-gold hover:underline">
              Register your company
            </Link>
          </p>
        </form>
      </main>
    </div>
  );
}
