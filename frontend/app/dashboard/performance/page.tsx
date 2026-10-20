"use client";

import { useEffect, useState } from "react";

import { PageHead, StateBlock, StatCard } from "@/components/agent/ui";
import { money } from "@/lib/agent";
import { api, endpoints, type AgentPerformance } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function AgentPerformancePage() {
  const { token } = useAuth();
  const [data, setData] = useState<AgentPerformance | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    api<AgentPerformance>(endpoints.agents.performance, { token })
      .then((payload) => {
        setData(payload);
        setError("");
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [token]);

  return (
    <div>
      <PageHead
        kicker="Performance"
        title="Factual link metrics"
        description="These counts come from recorded tracking events. Share intent is an in-app copy, not a confirmed social post."
      />
      <StateBlock loading={loading} error={error}>
        {data ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <StatCard label="Links" value={data.links} />
              <StatCard label="Opens" value={data.opens} />
              <StatCard label="Unique opens" value={data.unique_opens} />
              <StatCard label="Conversions" value={data.conversions} />
              <StatCard label="Gross commission" value={money(data.gross_commission)} />
              <StatCard label="Platform fees" value={money(data.platform_fees)} />
              <StatCard label="Net commission" value={money(data.net_commission)} />
              <StatCard label="Share intents (copied in MISA)" value={data.share_intents} />
            </div>
            {data.links === 0 ? (
              <p className="mt-8 rounded-2xl border border-dashed border-line bg-card px-5 py-10 text-center text-muted">
                No performance data yet. Create a tracking link to start recording opens and conversions.
              </p>
            ) : null}
          </>
        ) : null}
      </StateBlock>
    </div>
  );
}
