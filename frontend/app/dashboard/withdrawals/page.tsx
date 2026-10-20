"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  Field,
  inputClass,
  PageHead,
  primaryButtonClass,
  StateBlock,
  StatCard,
} from "@/components/agent/ui";
import { money } from "@/lib/agent";
import {
  api,
  endpoints,
  type AgentPayoutAccount,
  type AgentWithdrawal,
  type AgentWithdrawalsPayload,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AgentWithdrawalsPage() {
  const { token } = useAuth();
  const [wallet, setWallet] = useState<AgentWithdrawalsPayload | null>(null);
  const [accounts, setAccounts] = useState<AgentPayoutAccount[]>([]);
  const [amount, setAmount] = useState("");
  const [payoutAccount, setPayoutAccount] = useState("");
  const [label, setLabel] = useState("");
  const [destination, setDestination] = useState("");
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);

  const load = useCallback(() => {
    if (!token) return;
    Promise.all([
      api<AgentWithdrawalsPayload>(endpoints.agents.withdrawals, { token }),
      api<AgentPayoutAccount[]>(endpoints.agents.payoutAccounts, { token }),
    ])
      .then(([nextWallet, nextAccounts]) => {
        setWallet(nextWallet);
        setAccounts(nextAccounts);
        const defaultAccount = nextAccounts.find((row) => row.is_default) || nextAccounts[0];
        if (defaultAccount) setPayoutAccount(String(defaultAccount.id));
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  async function addDestination(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setPending(true);
    setFormError("");
    try {
      const created = await api<AgentPayoutAccount>(endpoints.agents.payoutAccounts, {
        method: "POST",
        token,
        body: JSON.stringify({
          label,
          destination_ref: destination,
          is_default: accounts.length === 0,
        }),
      });
      setLabel("");
      setDestination("");
      setAccounts((current) => [created, ...current]);
      setPayoutAccount(String(created.id));
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not save the destination.");
    } finally {
      setPending(false);
    }
  }

  async function requestPayout(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setPending(true);
    setFormError("");
    try {
      await api<AgentWithdrawal>(endpoints.agents.withdrawals, {
        method: "POST",
        token,
        body: JSON.stringify({
          amount,
          payout_account: payoutAccount ? Number(payoutAccount) : null,
        }),
      });
      setAmount("");
      load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not create the withdrawal.");
    } finally {
      setPending(false);
    }
  }

  const currency = wallet?.currency || "USD";

  return (
    <div>
      <PageHead
        kicker="Withdrawals"
        title="Request a payout"
        description="Withdrawals use your available balance from the backend ledger. No live payment provider is connected; staff complete payouts manually."
      />
      <StateBlock loading={loading} error={error}>
        {wallet ? (
          <>
            <div className="grid gap-4 sm:grid-cols-3">
              <StatCard label="Available" value={money(wallet.available_balance, currency)} />
              <StatCard label="Pending" value={money(wallet.pending_balance, currency)} />
              <StatCard
                label="Withdrawn"
                value={money(wallet.withdrawn_balance || wallet.paid_balance, currency)}
              />
            </div>

            <div className="mt-10 grid gap-8 lg:grid-cols-2">
              <form onSubmit={addDestination} className="space-y-4 rounded-2xl border border-line bg-card p-5">
                <h2 className="text-lg">Payout destination</h2>
                <Field label="Label">
                  <input className={inputClass} value={label} onChange={(event) => setLabel(event.target.value)} />
                </Field>
                <Field label="Account / reference">
                  <input
                    className={inputClass}
                    value={destination}
                    onChange={(event) => setDestination(event.target.value)}
                  />
                </Field>
                {formError ? <p className="text-sm text-error">{formError}</p> : null}
                <button type="submit" disabled={pending} className={primaryButtonClass}>
                  Save destination
                </button>
              </form>

              <form onSubmit={requestPayout} className="space-y-4 rounded-2xl border border-line bg-card p-5">
                <h2 className="text-lg">Create withdrawal</h2>
                <Field label="Amount">
                  <input
                    className={inputClass}
                    value={amount}
                    onChange={(event) => setAmount(event.target.value)}
                    inputMode="decimal"
                  />
                </Field>
                <Field label="Destination">
                  <select
                    className={inputClass}
                    value={payoutAccount}
                    onChange={(event) => setPayoutAccount(event.target.value)}
                  >
                    <option value="">Select a destination</option>
                    {accounts.map((account) => (
                      <option key={account.id} value={account.id}>
                        {account.label} · {account.destination_ref}
                      </option>
                    ))}
                  </select>
                </Field>
                {formError ? <p className="text-sm text-error">{formError}</p> : null}
                <button type="submit" disabled={pending || !amount} className={primaryButtonClass}>
                  Request withdrawal
                </button>
              </form>
            </div>

            <section className="mt-10">
              <h2 className="text-xl">History</h2>
              <div className="mt-4">
                <StateBlock
                  loading={false}
                  error=""
                  empty={wallet.withdrawals.length === 0}
                  emptyTitle="No withdrawals"
                  emptyBody="Requests will appear here with their backend status."
                >
                  <ul className="divide-y divide-line rounded-2xl border border-line bg-card">
                    {wallet.withdrawals.map((row) => (
                      <li key={row.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-4 text-sm">
                        <div>
                          <p className="font-medium">
                            {money(row.amount, row.currency)} · {row.status}
                          </p>
                          <p className="mt-1 text-muted">
                            {row.payout_account_label || row.destination_ref || "No destination"} ·{" "}
                            {new Date(row.requested_at).toLocaleString()}
                            {row.rejection_reason ? ` · ${row.rejection_reason}` : ""}
                          </p>
                        </div>
                        {row.status === "requested" && token ? (
                          <button
                            type="button"
                            disabled={pending}
                            onClick={async () => {
                              setPending(true);
                              setFormError("");
                              try {
                                await api(endpoints.agents.withdrawalCancel(row.id), { method: "POST", token });
                                load();
                              } catch (err) {
                                setFormError(
                                  err instanceof Error ? err.message : "Could not cancel the withdrawal.",
                                );
                              } finally {
                                setPending(false);
                              }
                            }}
                          >
                            Cancel
                          </button>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </StateBlock>
              </div>
            </section>
          </>
        ) : null}
      </StateBlock>
    </div>
  );
}
