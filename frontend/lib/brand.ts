import { endpoints, type BrandPerformanceFilters } from "./api";

export const BRAND_NAV_GROUPS = [
  {
    label: "Create",
    links: [
      { href: "/brand/studio", label: "Studio", icon: "＋" },
      { href: "/brand/studio/bulk", label: "Bulk Studio", icon: "▦" },
      { href: "/brand/videos", label: "Projects", icon: "▣" },
    ],
  },
  {
    label: "Catalog",
    links: [
      { href: "/brand/brands", label: "Brand", icon: "Aa" },
      { href: "/brand/products", label: "Products", icon: "◻" },
      { href: "/brand/characters", label: "Characters", icon: "Aa" },
    ],
  },
  {
    label: "Distribution",
    links: [
      { href: "/brand/teams", label: "Agent Teams", icon: "☰" },
      { href: "/brand/agents", label: "Agents", icon: "↗" },
      { href: "/brand/campaigns", label: "Campaigns", icon: "▦" },
      { href: "/brand/distribution", label: "Distribution", icon: "↗" },
      { href: "/brand/performance", label: "Performance", icon: "▣" },
      { href: "/brand/commissions", label: "Commissions", icon: "$" },
    ],
  },
  {
    label: "Account",
    links: [{ href: "/brand/profile", label: "Account", icon: "●" }],
  },
] as const;

export function isBrandNavActive(pathname: string, href: string) {
  if (href === "/brand/studio") {
    return pathname === href;
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export const BRAND_CREATED_NOTICE = "Brand created successfully";

export function mergeCreatedBrand<T extends { id: number }>(current: T[], saved: T): T[] {
  return [saved, ...current.filter((item) => item.id !== saved.id)];
}

export function performanceQuery(filters: BrandPerformanceFilters) {
  const query = new URLSearchParams();
  (Object.entries(filters) as [keyof BrandPerformanceFilters, string | undefined][]).forEach(
    ([key, value]) => {
      if (value) query.set(key, value);
    },
  );
  const suffix = query.toString();
  return `${endpoints.brands.performance}${suffix ? `?${suffix}` : ""}`;
}

export function previewQuery(params: {
  product: string;
  team?: string;
  agent?: string;
  campaign?: string;
}) {
  const query = new URLSearchParams();
  query.set("product", params.product);
  if (params.team) query.set("team", params.team);
  if (params.agent) query.set("agent", params.agent);
  if (params.campaign) query.set("campaign", params.campaign);
  return `${endpoints.brands.commissionPreview}?${query.toString()}`;
}

export function layerAmount(gross: string | null | undefined) {
  if (!gross) return "Not set";
  return gross;
}
