import { endpoints, type AgentLinkFilters, type AgentTeam } from "./api";

export const AGENT_NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/dashboard/brands", label: "Brands" },
  { href: "/dashboard/products", label: "Products" },
  { href: "/dashboard/teams", label: "My Teams" },
  { href: "/dashboard/links", label: "My Links" },
  { href: "/dashboard/performance", label: "Performance" },
  { href: "/dashboard/earnings", label: "Earnings" },
  { href: "/dashboard/withdrawals", label: "Withdrawals" },
  { href: "/dashboard/profile", label: "Profile" },
] as const;

export function isAgentNavActive(pathname: string, href: string) {
  if (href === "/dashboard") return pathname === "/dashboard";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function money(value: string | number | null | undefined, currency = "USD") {
  if (value === null || value === undefined || value === "") return "—";
  const amount = Number(value);
  if (Number.isNaN(amount)) return String(value);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

export function commissionLines(values: {
  gross?: string;
  fee?: string;
  net?: string;
  currency?: string;
}) {
  const currency = values.currency || "USD";
  return [
    `${money(values.gross ?? "0.00", currency)} gross`,
    `${money(values.fee ?? "0.00", currency)} MISA fee`,
    `${money(values.net ?? "0.00", currency)} agent earnings`,
  ];
}

export function eventLabel(eventType: string, fallback = "") {
  const labels: Record<string, string> = {
    created: "Link created",
    opened: "Open",
    clicked: "Click",
    share_intent: "Share intent (copied in MISA)",
    conversion: "Conversion",
    conversion_reversed: "Conversion reversed",
  };
  return labels[eventType] || fallback || eventType;
}

export function isShareIntent(eventType: string) {
  return eventType === "share_intent";
}

export type TeamAction = "none" | "join" | "cancel" | "accept";

export function teamAction(team: Pick<
  AgentTeam,
  "can_join" | "can_cancel_request" | "can_accept_invitation" | "membership_status"
>): TeamAction {
  if (team.membership_status === "active") return "none";
  if (team.can_accept_invitation) return "accept";
  if (team.can_cancel_request) return "cancel";
  if (team.can_join) return "join";
  return "none";
}

export function teamStatusLabel(team: Pick<
  AgentTeam,
  "membership_status" | "join_request_status" | "invitation_status"
>) {
  if (team.membership_status === "active") return "Active member";
  if (team.invitation_status === "pending") return "Invitation pending";
  if (team.join_request_status === "pending") return "Join request pending";
  if (team.join_request_status === "rejected") return "Request rejected";
  if (team.invitation_status === "declined") return "Invitation declined";
  return "Not a member";
}

export function linkQuery(filters: AgentLinkFilters) {
  const query = new URLSearchParams();
  (Object.entries(filters) as [keyof AgentLinkFilters, string | undefined][]).forEach(
    ([key, value]) => {
      if (value) query.set(key, value);
    },
  );
  const suffix = query.toString();
  return `${endpoints.agents.links}${suffix ? `?${suffix}` : ""}`;
}

export function emptyDashboard(data: {
  recent_activity: unknown[];
  top_products: unknown[];
  active_teams: unknown[];
}) {
  return {
    activity: data.recent_activity.length === 0,
    products: data.top_products.length === 0,
    teams: data.active_teams.length === 0,
  };
}
