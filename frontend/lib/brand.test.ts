import { describe, expect, it } from "vitest";

import { endpoints } from "./api";
import { BRAND_CREATED_NOTICE, BRAND_NAV_GROUPS, isBrandNavActive, mergeCreatedBrand } from "./brand";

describe("brand workspace nav", () => {
  it("adds distribution management without replacing studio", () => {
    const labels = BRAND_NAV_GROUPS.flatMap((group) => group.links.map((link) => link.label));
    expect(labels).toEqual([
      "Studio",
      "Bulk Studio",
      "Projects",
      "Brand",
      "Products",
      "Characters",
      "Agent Teams",
      "Agents",
      "Campaigns",
      "Distribution",
      "Performance",
      "Commissions",
      "Account",
    ]);
    expect(isBrandNavActive("/brand/studio", "/brand/studio")).toBe(true);
    expect(isBrandNavActive("/brand/studio/bulk", "/brand/studio")).toBe(false);
    expect(isBrandNavActive("/brand/studio/bulk", "/brand/studio/bulk")).toBe(true);
    expect(isBrandNavActive("/brand/teams/3", "/brand/teams")).toBe(true);
    expect(isBrandNavActive("/brand/agents", "/brand/studio")).toBe(false);
  });

  it("keeps a created brand in the list and uses the same product catalog as Studio", () => {
    const brands = [{ id: 1, name: "MiSa" }];
    const next = mergeCreatedBrand(brands, { id: 12, name: "Penang Air Kitchen QA" });
    expect(next.map((item) => item.id)).toEqual([12, 1]);
    expect(BRAND_CREATED_NOTICE).toBe("Brand created successfully");
    expect(endpoints.brands.products).toContain("/api/brands/products/");
    expect(endpoints.brands.productsQuery({})).toBe(endpoints.brands.products);
    expect(endpoints.brands.productsQuery({ brand: "1" })).toContain("brand=1");
  });
});
