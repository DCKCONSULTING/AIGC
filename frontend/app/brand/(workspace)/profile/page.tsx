"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  api,
  endpoints,
  type Brand,
  type BrandOwnerProfile,
  type Category,
  type ProfileUpdatePayload,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

type FormState = {
  company_name: string;
  company_website: string;
  company_description: string;
  company_location: string;
  company_category: string;
  name: string;
  username: string;
  email: string;
  mobile: string;
  location: string;
  current_password: string;
  password: string;
  password_confirm: string;
};

const emptyForm: FormState = {
  company_name: "",
  company_website: "",
  company_description: "",
  company_location: "",
  company_category: "",
  name: "",
  username: "",
  email: "",
  mobile: "",
  location: "",
  current_password: "",
  password: "",
  password_confirm: "",
};

function companyOf(
  profile: BrandOwnerProfile | null,
  actingBrandId?: number | null,
): Brand | null {
  if (!profile) return null;
  if (profile.company) return profile.company;
  if (actingBrandId) {
    return profile.brands.find((brand) => brand.id === actingBrandId) || null;
  }
  return [...profile.brands].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  )[0] || null;
}

export default function BrandProfilePage() {
  const { user, token, actingAccount, applyProfile } = useAuth();
  const [profile, setProfile] = useState<BrandOwnerProfile | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!token) return;
    Promise.all([
      api<BrandOwnerProfile>(endpoints.brands.me, { token }),
      api<Category[]>(endpoints.brands.categories, { token }),
    ]).then(([nextProfile, nextCategories]) => {
      setProfile(nextProfile);
      setCategories(nextCategories);
    });
  }, [token]);

  const display = profile ?? user;
  const company = companyOf(profile, actingAccount?.brandId);
  const companyName = actingAccount?.name || company?.name || "Brand owner";

  const details = useMemo(
    () => [
      ["Company", companyName],
      ["Website", company?.website || ""],
      ["Category", company?.category_name || ""],
      ["Company location", company?.location || ""],
      ["What you sell", company?.description || ""],
      ["Contact name", display?.name || ""],
      ["Username", display?.username || ""],
      ["Email", display?.email || ""],
      ["Mobile", display?.mobile || ""],
      ["Contact location", display?.location || ""],
      ["Account type", "Brand owner"],
    ],
    [company, companyName, display],
  );

  if (!user) return null;

  function openEdit() {
    if (!display) return;
    setError("");
    setForm({
      company_name: company?.name || "",
      company_website: company?.website || "",
      company_description: company?.description || "",
      company_location: company?.location || "",
      company_category: company?.category ? String(company.category) : "",
      name: display.name || "",
      username: display.username || "",
      email: display.email || "",
      mobile: display.mobile || "",
      location: display.location || "",
      current_password: "",
      password: "",
      password_confirm: "",
    });
    setEditing(true);
  }

  function closeEdit() {
    if (pending) return;
    setEditing(false);
    setError("");
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    setError("");
    setPending(true);
    const payload: ProfileUpdatePayload = {
      name: form.name,
      username: form.username,
      email: form.email,
      mobile: form.mobile,
      location: form.location,
      company: {
        name: form.company_name,
        website: form.company_website,
        description: form.company_description,
        location: form.company_location,
        category: Number(form.company_category),
      },
    };
    if (form.password || form.password_confirm || form.current_password) {
      payload.current_password = form.current_password;
      payload.password = form.password;
      payload.password_confirm = form.password_confirm;
    }
    try {
      const updated = await api<BrandOwnerProfile>(endpoints.brands.me, {
        method: "PATCH",
        token,
        body: JSON.stringify(payload),
      });
      setProfile(updated);
      applyProfile(updated);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save profile.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-gold">Profile</p>
          <h1 className="mt-3 font-serif text-4xl">Your account</h1>
          <p className="mt-3 text-muted">
            Edit your login details and company information from here.
          </p>
        </div>
        <button
          type="button"
          onClick={openEdit}
          className="h-11 shrink-0 rounded-full bg-gold px-5 text-sm font-medium hover:bg-gold-deep"
        >
          Edit
        </button>
      </div>
      <dl className="mt-8 grid gap-4 rounded-2xl border border-line bg-card p-8 sm:grid-cols-2">
        {details.map(([label, value]) => (
          <div
            key={label}
            className={label === "What you sell" ? "sm:col-span-2" : undefined}
          >
            <dt className="text-xs uppercase tracking-[0.16em] text-muted">
              {label}
            </dt>
            <dd className="mt-1 text-lg">
              {label === "Website" && value ? (
                <a
                  href={value}
                  className="text-gold hover:underline"
                  target="_blank"
                  rel="noreferrer"
                >
                  {value.replace(/^https?:\/\//, "")}
                </a>
              ) : (
                value || "—"
              )}
            </dd>
          </div>
        ))}
      </dl>

      {editing ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            className="absolute inset-0 bg-black/30"
            aria-label="Close"
            onClick={closeEdit}
          />
          <form
            onSubmit={onSubmit}
            className="relative max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-line bg-card p-6 shadow-lg"
          >
            <h2 className="font-serif text-2xl">Edit profile</h2>
            <p className="mt-1 text-sm text-muted">
              Update company details, contact information, username, or password.
            </p>
            {error ? (
              <p className="mt-4 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700">
                {error}
              </p>
            ) : null}
            <div className="mt-5 grid gap-4">
              <p className="text-xs uppercase tracking-[0.16em] text-muted">
                Company
              </p>
              <label className="block text-sm">
                Company name
                <input
                  required
                  value={form.company_name}
                  onChange={(event) =>
                    setForm({ ...form, company_name: event.target.value })
                  }
                  autoComplete="organization"
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
              <label className="block text-sm">
                Category
                <select
                  required
                  value={form.company_category}
                  onChange={(event) =>
                    setForm({ ...form, company_category: event.target.value })
                  }
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                >
                  <option value="" disabled>
                    Select a category
                  </option>
                  {categories.map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-sm">
                Website
                <input
                  value={form.company_website}
                  onChange={(event) =>
                    setForm({ ...form, company_website: event.target.value })
                  }
                  placeholder="https://yourbrand.com"
                  autoComplete="url"
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
              <label className="block text-sm">
                Company location
                <input
                  required
                  value={form.company_location}
                  onChange={(event) =>
                    setForm({ ...form, company_location: event.target.value })
                  }
                  placeholder="City, country"
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
              <label className="block text-sm">
                What does your company sell?
                <textarea
                  required
                  minLength={10}
                  rows={3}
                  value={form.company_description}
                  onChange={(event) =>
                    setForm({ ...form, company_description: event.target.value })
                  }
                  className="mt-2 w-full rounded-xl border border-line bg-background px-4 py-3 outline-none focus:border-gold"
                />
              </label>
              <p className="pt-2 text-xs uppercase tracking-[0.16em] text-muted">
                Contact
              </p>
              <label className="block text-sm">
                Contact name
                <input
                  required
                  value={form.name}
                  onChange={(event) =>
                    setForm({ ...form, name: event.target.value })
                  }
                  autoComplete="name"
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
              <label className="block text-sm">
                Username
                <input
                  required
                  value={form.username}
                  onChange={(event) =>
                    setForm({ ...form, username: event.target.value })
                  }
                  autoComplete="username"
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
              <label className="block text-sm">
                Email
                <input
                  required
                  type="email"
                  value={form.email}
                  onChange={(event) =>
                    setForm({ ...form, email: event.target.value })
                  }
                  autoComplete="email"
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm">
                  Mobile
                  <input
                    required
                    type="tel"
                    value={form.mobile}
                    onChange={(event) =>
                      setForm({ ...form, mobile: event.target.value })
                    }
                    autoComplete="tel"
                    className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                  />
                </label>
                <label className="block text-sm">
                  Contact location
                  <input
                    required
                    value={form.location}
                    onChange={(event) =>
                      setForm({ ...form, location: event.target.value })
                    }
                    autoComplete="address-level2"
                    className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                  />
                </label>
              </div>
              <p className="pt-2 text-xs uppercase tracking-[0.16em] text-muted">
                Password
              </p>
              <p className="text-sm text-muted">
                Leave blank to keep your current password.
              </p>
              <label className="block text-sm">
                Current password
                <input
                  type="password"
                  required={Boolean(form.password || form.password_confirm)}
                  value={form.current_password}
                  onChange={(event) =>
                    setForm({ ...form, current_password: event.target.value })
                  }
                  autoComplete="current-password"
                  className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                />
              </label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm">
                  New password
                  <input
                    minLength={8}
                    type="password"
                    value={form.password}
                    onChange={(event) =>
                      setForm({ ...form, password: event.target.value })
                    }
                    autoComplete="new-password"
                    className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                  />
                </label>
                <label className="block text-sm">
                  Confirm password
                  <input
                    minLength={8}
                    required={Boolean(form.password)}
                    type="password"
                    value={form.password_confirm}
                    onChange={(event) =>
                      setForm({ ...form, password_confirm: event.target.value })
                    }
                    autoComplete="new-password"
                    className="mt-2 h-11 w-full rounded-xl border border-line bg-background px-4 outline-none focus:border-gold"
                  />
                </label>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={closeEdit}
                disabled={pending}
                className="h-11 rounded-full border border-line px-5 text-sm hover:bg-black/5"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={pending}
                className="h-11 rounded-full bg-gold px-5 text-sm font-medium hover:bg-gold-deep disabled:opacity-60"
              >
                {pending ? "Saving…" : "Save changes"}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}
