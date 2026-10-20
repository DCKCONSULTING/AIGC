import { commissionLines, money } from "@/lib/agent";

export function PageHead({
  kicker,
  title,
  description,
}: {
  kicker: string;
  title: string;
  description?: string;
}) {
  return (
    <div className="workspace-page-head">
      <p className="text-[11px] font-extrabold uppercase tracking-[0.18em] text-[#7b879c]">
        {kicker}
      </p>
      <h1 className="mt-2 font-serif text-4xl text-[var(--misa-navy)]">{title}</h1>
      {description ? <p className="mt-3 max-w-2xl text-muted">{description}</p> : null}
    </div>
  );
}

export function StateBlock({
  loading,
  error,
  empty,
  emptyTitle,
  emptyBody,
  children,
}: {
  loading: boolean;
  error: string;
  empty?: boolean;
  emptyTitle?: string;
  emptyBody?: string;
  children: React.ReactNode;
}) {
  if (loading) {
    return <p className="rounded-2xl border border-line bg-card px-5 py-10 text-center text-muted">Loading…</p>;
  }
  if (error) {
    return (
      <p className="rounded-2xl border border-error/20 bg-error/5 px-5 py-10 text-center text-error">
        {error}
      </p>
    );
  }
  if (empty) {
    return (
      <div className="rounded-2xl border border-dashed border-line bg-card px-6 py-16 text-center">
        <p className="text-lg text-[var(--misa-navy)]">{emptyTitle || "Nothing here yet"}</p>
        {emptyBody ? <p className="mt-2 text-muted">{emptyBody}</p> : null}
      </div>
    );
  }
  return <>{children}</>;
}

export function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-2xl border border-line bg-card p-5">
      <p className="text-[11px] font-extrabold uppercase tracking-[0.16em] text-muted">{label}</p>
      <p className="mt-2 text-2xl text-[var(--misa-navy)]">{value}</p>
    </div>
  );
}

export function CommissionBlock({
  gross,
  fee,
  net,
  currency = "USD",
}: {
  gross?: string | null;
  fee?: string | null;
  net?: string | null;
  currency?: string;
}) {
  return (
    <ul className="space-y-1 text-sm">
      {commissionLines({
        gross: gross ?? "0.00",
        fee: fee ?? "0.00",
        net: net ?? "0.00",
        currency,
      }).map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}

export function Money({ value, currency = "USD" }: { value: string; currency?: string }) {
  return <span>{money(value, currency)}</span>;
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-muted">{label}</span>
      {children}
    </label>
  );
}

export const inputClass =
  "h-11 w-full rounded-xl border border-line bg-white px-3 text-sm outline-none focus:border-[var(--misa-blue)]";

export const primaryButtonClass =
  "inline-flex h-11 items-center rounded-full bg-gold px-5 text-sm font-medium text-foreground hover:bg-gold-deep disabled:opacity-50";

export const secondaryButtonClass =
  "inline-flex h-11 items-center rounded-full border border-line bg-card px-5 text-sm hover:bg-black/5 disabled:opacity-50";
