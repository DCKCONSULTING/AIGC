"use client";

import type { ButtonHTMLAttributes } from "react";

export function CheckMark({ ok }: { ok: boolean }) {
  return <StatusMark status={ok ? "passed" : "failed"} />;
}

export function StatusMark({ status }: { status: string }) {
  const mark =
    status === "passed"
      ? "✓"
      : status === "failed"
        ? "!"
        : status === "warning"
          ? "⚠"
          : status === "skipped"
            ? "○"
            : "–";
  const label =
    status === "passed"
      ? "PASS"
      : status === "failed"
        ? "FAIL"
        : status === "warning"
          ? "WARNING"
          : status === "skipped"
            ? "SKIPPED"
            : "NOT CHECKED";
  const tone =
    status === "passed"
      ? "bg-[#e7fbff] text-[#08798d]"
      : status === "failed"
        ? "bg-[#fff0f6] text-[#b71958]"
        : status === "warning"
          ? "bg-[#fff8dd] text-[#88620c]"
          : "bg-[#f0f3f7] text-muted";
  return (
    <span
      className={`inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-medium ${tone}`}
      aria-label={label}
    >
      {mark}
    </span>
  );
}

export function ChoiceButton({
  selected,
  title,
  hint,
  onClick,
}: {
  selected: boolean;
  title: string;
  hint?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`min-h-12 rounded-2xl border px-4 py-3 text-left transition ${
        selected
          ? "border-[var(--misa-cyan)] bg-[linear-gradient(135deg,#f0fcff_0%,#f7f4ff_68%,#fff5fa_100%)]"
          : "border-line bg-card hover:bg-[#f1f8ff]"
      }`}
    >
      <p className="font-medium">{title}</p>
      {hint ? <p className="mt-1 text-sm text-muted">{hint}</p> : null}
    </button>
  );
}

export function PrimaryButton({
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`h-12 rounded-[12px] bg-[linear-gradient(110deg,#0874f9,#1764ef_55%,#7658f4)] px-6 text-sm font-medium text-white shadow-[0_4px_0_#064bb6,0_12px_26px_rgba(8,116,249,0.2)] hover:shadow-[0_6px_0_#064bb6,0_16px_32px_rgba(8,116,249,0.25)] disabled:opacity-60 ${props.className || ""}`}
    >
      {children}
    </button>
  );
}

export function SecondaryButton({
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className={`h-12 rounded-[12px] border border-[#d8e1ee] bg-white px-6 text-sm text-[#2f3b57] hover:border-[#8c98ab] disabled:opacity-40 ${props.className || ""}`}
    >
      {children}
    </button>
  );
}
