"use client";

import { useState } from "react";

import { primaryButtonClass, secondaryButtonClass } from "@/components/agent/ui";
import { teamAction, teamStatusLabel } from "@/lib/agent";
import { api, endpoints, type AgentTeam } from "@/lib/api";

export function TeamActions({
  team,
  token,
  onChange,
}: {
  team: AgentTeam;
  token: string;
  onChange: () => void;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const action = teamAction(team);

  async function run(task: () => Promise<unknown>) {
    setPending(true);
    setError("");
    try {
      await task();
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className="text-sm text-muted">{teamStatusLabel(team)}</span>
      {action === "join" ? (
        <button
          type="button"
          disabled={pending}
          className={primaryButtonClass}
          onClick={() =>
            run(() => api(endpoints.agents.teamJoin(team.id), { method: "POST", token, body: JSON.stringify({}) }))
          }
        >
          Request to join
        </button>
      ) : null}
      {action === "cancel" && team.join_request_id ? (
        <button
          type="button"
          disabled={pending}
          className={secondaryButtonClass}
          onClick={() =>
            run(() =>
              api(endpoints.agents.joinRequestCancel(team.join_request_id as number), {
                method: "POST",
                token,
              }),
            )
          }
        >
          Cancel request
        </button>
      ) : null}
      {action === "accept" && team.invitation_id ? (
        <>
          <button
            type="button"
            disabled={pending}
            className={primaryButtonClass}
            onClick={() =>
              run(() =>
                api(endpoints.agents.invitationAccept(team.invitation_id as number), {
                  method: "POST",
                  token,
                }),
              )
            }
          >
            Accept invitation
          </button>
          <button
            type="button"
            disabled={pending}
            className={secondaryButtonClass}
            onClick={() =>
              run(() =>
                api(endpoints.agents.invitationDecline(team.invitation_id as number), {
                  method: "POST",
                  token,
                }),
              )
            }
          >
            Decline
          </button>
        </>
      ) : null}
      {error ? <p className="w-full text-sm text-error">{error}</p> : null}
    </div>
  );
}
