import { money } from "@/lib/agent";
import type { BrandCommissionPreview } from "@/lib/api";

const ORDER = ["default", "team", "agent", "campaign"] as const;

export function CommissionLayers({
  preview,
}: {
  preview: BrandCommissionPreview | null;
}) {
  if (!preview) {
    return <p className="text-sm text-muted">Select a product to see the effective commission.</p>;
  }
  return (
    <div className="rounded-2xl border border-line bg-card p-5">
      <p className="text-[11px] font-extrabold uppercase tracking-[0.16em] text-muted">
        Effective commission
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        {ORDER.filter((key) => key !== "campaign" || preview.layers.campaign.configured).map((key) => {
          const layer = preview.layers[key];
          return (
            <div
              key={key}
              className={`rounded-xl border px-4 py-3 ${
                layer.effective ? "border-gold bg-gold/10" : "border-line bg-white"
              }`}
            >
              <p className="text-xs uppercase tracking-[0.14em] text-muted">{layer.label}</p>
              <p className="mt-1 text-xl text-[var(--misa-navy)]">
                {layer.configured ? money(layer.gross) : "Not set"}
              </p>
              {layer.effective ? (
                <p className="mt-1 text-xs font-medium text-gold">Currently effective</p>
              ) : null}
            </div>
          );
        })}
      </div>
      {preview.effective ? (
        <p className="mt-4 text-sm text-muted">
          Paying {money(preview.effective.gross)} gross · {money(preview.effective.platform_fee)} MISA
          fee · {money(preview.effective.net)} agent net.
        </p>
      ) : (
        <p className="mt-4 text-sm text-muted">No commission rule applies yet.</p>
      )}
    </div>
  );
}
