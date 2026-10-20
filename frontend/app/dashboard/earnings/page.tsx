"use client";

import { useEffect, useState } from "react";

import { CommissionBlock, PageHead, StateBlock, StatCard } from "@/components/agent/ui";
import { money } from "@/lib/agent";
import { api, endpoints, type AgentCommissionTransaction, type AgentEarnings } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function TransactionList({
  rows,
  emptyTitle,
}: {
  rows: AgentCommissionTransaction[];
  emptyTitle: string;
}) {
  if (!rows.length) {
    return (
      <p className="rounded-2xl border border-dashed border-line bg-card px-5 py-8 text-center text-muted">
        {emptyTitle}
      </p>
    );
  }
  return (
    <ul className="space-y-3">
      {rows.map((row) => (
        <li key={row.id} className="rounded-2xl border border-line bg-card p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <p className="font-medium">{row.product_name}</p>
              <p className="text-sm text-muted">
                {row.brand_name} · {row.team_name} · {row.status}
                {row.tracking_code ? ` · ${row.tracking_code}` : ""}
              </p>
            </div>
            <p className="text-sm text-muted">{new Date(row.created_at).toLocaleString()}</p>
          </div>
          <div className="mt-3">
            <CommissionBlock
              gross={row.gross_amount}
              fee={row.platform_fee_amount}
              net={row.agent_net_amount}
              currency={row.currency}
            />
          </div>
        </li>
      ))}
    </ul>
  );
}

export default function AgentEarningsPage() {
  const { token } = useAuth();
  const [data, setData] = useState<AgentEarnings | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    api<AgentEarnings>(endpoints.agents.earnings, { token })
      .then((payload) => {
        setData(payload);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token]);

  const currency = data?.currency || "USD";

  return (
    <div>
      <PageHead
        kicker="Earnings"
        title="Pending, available, and withdrawn"
        description="Each transaction shows gross commission, the MISA fee, and your net from the snapshot recorded at conversion. Withdrawn is ledger accounting only; staff complete payouts manually. No payment provider is connected."
      />
      <StateBlock loading={loading} error={error}>
        {data ? (
          <>
            <div className="grid gap-4 sm:grid-cols-3">
              <StatCard label="Pending" value={money(data.pending_balance, currency)} />
              <StatCard label="Available" value={money(data.available_balance, currency)} />
              <StatCard
                label="Withdrawn"
                value={money(data.withdrawn_balance || data.paid_balance, currency)}
              />
            </div>
            <section className="mt-10">
              <h2 className="text-xl">Pending</h2>
              <div className="mt-4">
                <TransactionList rows={data.pending} emptyTitle="No pending commissions." />
              </div>
            </section>
            <section className="mt-10">
              <h2 className="text-xl">Available</h2>
              <div className="mt-4">
                <TransactionList rows={data.available} emptyTitle="No available commissions." />
              </div>
            </section>
            <section className="mt-10">
              <h2 className="text-xl">Transaction history</h2>
              <div className="mt-4">
                <TransactionList rows={data.transactions} emptyTitle="No commission transactions yet." />
              </div>
            </section>
          </>
        ) : null}
      </StateBlock>
    </div>
  );
}
