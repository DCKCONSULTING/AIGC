"use client";

import { FormEvent, useEffect, useState } from "react";

import { Field, inputClass, PageHead, primaryButtonClass, StateBlock } from "@/components/agent/ui";
import { api, endpoints, type AgentProfile } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type FormState = {
  name: string;
  username: string;
  email: string;
  mobile: string;
  location: string;
  bio: string;
  current_password: string;
  password: string;
  password_confirm: string;
};

const emptyForm: FormState = {
  name: "",
  username: "",
  email: "",
  mobile: "",
  location: "",
  bio: "",
  current_password: "",
  password: "",
  password_confirm: "",
};

export default function AgentProfilePage() {
  const { token, applyProfile } = useAuth();
  const [profile, setProfile] = useState<AgentProfile | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [editing, setEditing] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!token) return;
    api<AgentProfile>(endpoints.agents.me, { token })
      .then((payload) => {
        setProfile(payload);
        setForm({
          ...emptyForm,
          name: payload.user.name,
          username: payload.user.username,
          email: payload.user.email,
          mobile: payload.user.mobile,
          location: payload.user.location,
          bio: payload.bio,
        });
        setLoadError("");
      })
      .catch((err: Error) => setLoadError(err.message))
      .finally(() => setLoading(false));
  }, [token]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setPending(true);
    setSaveError("");
    try {
      const payload = await api<AgentProfile>(endpoints.agents.me, {
        method: "PATCH",
        token,
        body: JSON.stringify(form),
      });
      setProfile(payload);
      applyProfile(payload.user);
      setEditing(false);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not update your profile.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <PageHead kicker="Profile" title="Your agent account" />
      <StateBlock loading={loading} error={loadError}>
        {profile ? (
          <div className="rounded-2xl border border-line bg-card p-6">
            {editing ? (
              <form onSubmit={save} className="grid gap-4 sm:grid-cols-2">
                <Field label="Name">
                  <input
                    className={inputClass}
                    value={form.name}
                    onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                  />
                </Field>
                <Field label="Username">
                  <input
                    className={inputClass}
                    value={form.username}
                    onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))}
                  />
                </Field>
                <Field label="Email">
                  <input
                    className={inputClass}
                    value={form.email}
                    onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
                  />
                </Field>
                <Field label="Mobile">
                  <input
                    className={inputClass}
                    value={form.mobile}
                    onChange={(event) => setForm((current) => ({ ...current, mobile: event.target.value }))}
                  />
                </Field>
                <Field label="Location">
                  <input
                    className={inputClass}
                    value={form.location}
                    onChange={(event) => setForm((current) => ({ ...current, location: event.target.value }))}
                  />
                </Field>
                <div className="sm:col-span-2">
                  <Field label="Bio">
                    <textarea
                      className={`${inputClass} h-28 py-3`}
                      value={form.bio}
                      onChange={(event) => setForm((current) => ({ ...current, bio: event.target.value }))}
                    />
                  </Field>
                </div>
                <Field label="Current password">
                  <input
                    type="password"
                    className={inputClass}
                    value={form.current_password}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, current_password: event.target.value }))
                    }
                  />
                </Field>
                <Field label="New password">
                  <input
                    type="password"
                    className={inputClass}
                    value={form.password}
                    onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
                  />
                </Field>
                <Field label="Confirm password">
                  <input
                    type="password"
                    className={inputClass}
                    value={form.password_confirm}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, password_confirm: event.target.value }))
                    }
                  />
                </Field>
                {saveError ? <p className="sm:col-span-2 text-sm text-error">{saveError}</p> : null}
                <div className="sm:col-span-2 flex gap-3">
                  <button type="submit" disabled={pending} className={primaryButtonClass}>
                    Save
                  </button>
                  <button type="button" className="text-sm text-muted" onClick={() => setEditing(false)}>
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              <dl className="grid gap-4 sm:grid-cols-2">
                {[
                  ["Name", profile.user.name],
                  ["Username", profile.user.username],
                  ["Email", profile.user.email],
                  ["Mobile", profile.user.mobile],
                  ["Location", profile.user.location],
                  ["Status", profile.status],
                  ["Bio", profile.bio || "—"],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-xs uppercase tracking-[0.16em] text-muted">{label}</dt>
                    <dd className="mt-1">{value}</dd>
                  </div>
                ))}
                <div className="sm:col-span-2">
                  <button type="button" className={primaryButtonClass} onClick={() => setEditing(true)}>
                    Edit profile
                  </button>
                </div>
              </dl>
            )}
          </div>
        ) : null}
      </StateBlock>
    </div>
  );
}
