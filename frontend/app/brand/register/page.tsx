"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { DraftNotice } from "@/components/home/DraftNotice";
import { SiteHeader } from "@/components/SiteHeader";
import { useAuth } from "@/lib/auth";
import { homePath, safeNextPath } from "@/lib/paths";

type FormState = {
  name: string;
  username: string;
  email: string;
  mobile: string;
  location: string;
  company_name: string;
  company_website: string;
  company_description: string;
  password: string;
  password_confirm: string;
};

const emptyForm: FormState = {
  name: "",
  username: "",
  email: "",
  mobile: "",
  location: "",
  company_name: "",
  company_website: "",
  company_description: "",
  password: "",
  password_confirm: "",
};

const contactFields = [
  { key: "name", label: "Contact name", autoComplete: "name", type: "text" },
  { key: "username", label: "Username", autoComplete: "username", type: "text" },
  { key: "email", label: "Email", autoComplete: "email", type: "email" },
  { key: "mobile", label: "Mobile number", autoComplete: "tel", type: "tel" },
] as const;

export default function BrandRegisterPage() {
  const router = useRouter();
  const { registerBrand, user, ready, workspace, actingAccount } = useAuth();
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (ready && user) {
      const destination = safeNextPath(new URLSearchParams(window.location.search).get("next"));
      router.replace(user.role === "producer" && destination ? destination : homePath(user, workspace, actingAccount));
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
      await registerBrand(form);
      const destination = safeNextPath(new URLSearchParams(window.location.search).get("next"));
      router.push(destination || "/brand/studio");
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
            Brand registration
          </p>
          <h1 className="mt-4 font-serif text-5xl leading-tight">
            Register your company and start creating.
          </h1>
          <p className="mt-5 max-w-md text-muted">
            Tell us who you are and what your company makes. You will log in
            with your username or email.
          </p>
        </div>

        <form
          onSubmit={onSubmit}
          className="rounded-3xl border border-line bg-card p-8"
        >
          <h2 className="font-serif text-3xl">Create brand account</h2>
          <DraftNotice />

          {error ? (
            <p className="mt-5 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </p>
          ) : null}

          <p className="mt-6 text-xs uppercase tracking-[0.16em] text-muted">
            Contact
          </p>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            {contactFields.map((field) => (
              <label key={field.key} className="block text-sm">
                {field.label}
                <input
                  required
                  type={field.type}
                  autoComplete={field.autoComplete}
                  value={form[field.key]}
                  onChange={(event) => update(field.key, event.target.value)}
                  className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
            ))}
          </div>

          <p className="mt-8 text-xs uppercase tracking-[0.16em] text-muted">
            Company
          </p>
          <div className="mt-3 grid gap-4">
            <label className="block text-sm">
              Company name
              <input
                required
                value={form.company_name}
                onChange={(event) => update("company_name", event.target.value)}
                autoComplete="organization"
                className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              />
            </label>
            <label className="block text-sm">
              Company website
              <input
                value={form.company_website}
                onChange={(event) => update("company_website", event.target.value)}
                autoComplete="url"
                placeholder="https://yourbrand.com"
                className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              />
            </label>
            <label className="block text-sm">
              Location
              <input
                required
                value={form.location}
                onChange={(event) => update("location", event.target.value)}
                autoComplete="address-level2"
                placeholder="City, country"
                className="mt-2 h-12 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
              />
            </label>
            <label className="block text-sm">
              What does your company sell?
              <textarea
                required
                minLength={10}
                rows={4}
                value={form.company_description}
                onChange={(event) =>
                  update("company_description", event.target.value)
                }
                placeholder="Products, category, and who you want to reach."
                className="mt-2 w-full rounded-xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
              />
            </label>
          </div>

          <p className="mt-8 text-xs uppercase tracking-[0.16em] text-muted">
            Password
          </p>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
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
            {pending ? "Creating account…" : "Create brand account"}
          </button>

          <p className="mt-5 text-center text-sm text-muted">
            Already registered?{" "}
            <Link href="/brand/login" className="text-gold hover:underline">
              Brand log in
            </Link>
          </p>
          <p className="mt-2 text-center text-sm text-muted">
            Agent?{" "}
            <Link href="/register" className="text-gold hover:underline">
              Create an agent account
            </Link>
          </p>
        </form>
      </main>
    </div>
  );
}
