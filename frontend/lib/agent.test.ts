import { describe, expect, it } from "vitest";

import { endpoints } from "./api";
import {
  AGENT_NAV,
  commissionLines,
  emptyDashboard,
  eventLabel,
  isAgentNavActive,
  isShareIntent,
  linkQuery,
  money,
  teamAction,
  teamStatusLabel,
} from "./agent";

describe("agent workspace helpers", () => {
  it("keeps dashboard nav from matching nested routes", () => {
    expect(isAgentNavActive("/dashboard", "/dashboard")).toBe(true);
    expect(isAgentNavActive("/dashboard/links", "/dashboard")).toBe(false);
    expect(isAgentNavActive("/dashboard/brands/3", "/dashboard/brands")).toBe(true);
    expect(AGENT_NAV.map((item) => item.label)).toEqual([
      "Dashboard",
      "Brands",
      "Products",
      "My Teams",
      "My Links",
      "Performance",
      "Earnings",
      "Withdrawals",
      "Profile",
    ]);
  });

  it("formats commission breakdown from backend amounts", () => {
    expect(money("1.00")).toBe("$1.00");
    expect(commissionLines({ gross: "1.00", fee: "0.03", net: "0.97" })).toEqual([
      "$1.00 gross",
      "$0.03 MISA fee",
      "$0.97 agent earnings",
    ]);
  });

  it("labels in-app copy as share intent, not a social post", () => {
    expect(eventLabel("share_intent")).toBe("Share intent (copied in MISA)");
    expect(isShareIntent("share_intent")).toBe(true);
    expect(isShareIntent("opened")).toBe(false);
  });

  it("prevents duplicate join actions from backend state", () => {
    expect(
      teamAction({
        membership_status: "active",
        can_join: false,
        can_cancel_request: false,
        can_accept_invitation: false,
      }),
    ).toBe("none");
    expect(
      teamAction({
        membership_status: "",
        can_join: false,
        can_cancel_request: true,
        can_accept_invitation: false,
      }),
    ).toBe("cancel");
    expect(
      teamAction({
        membership_status: "",
        can_join: false,
        can_cancel_request: false,
        can_accept_invitation: true,
      }),
    ).toBe("accept");
    expect(
      teamStatusLabel({
        membership_status: "",
        join_request_status: "pending",
        invitation_status: "",
      }),
    ).toBe("Join request pending");
  });

  it("builds link filters without inventing extra metrics", () => {
    expect(linkQuery({ product: "4", status: "active" })).toBe(
      `${endpoints.agents.links}?product=4&status=active`,
    );
    expect(emptyDashboard({ recent_activity: [], top_products: [], active_teams: [] })).toEqual({
      activity: true,
      products: true,
      teams: true,
    });
  });
});
