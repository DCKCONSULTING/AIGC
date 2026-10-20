import { describe, expect, it } from "vitest";

import {
  canAccessAgent,
  canAccessBrand,
  homePath,
  postLoginPath,
  safeNextPath,
} from "./paths";
import type { Account, ActingAccount } from "./api";

const superuser: Account = {
  id: 1,
  username: "admin",
  name: "Admin",
  email: "admin@example.com",
  mobile: "012",
  location: "KL",
  role: "agent",
  is_superuser: true,
};

const brandUser: Account = { ...superuser, id: 2, is_superuser: false, role: "producer" };
const agentUser: Account = { ...superuser, id: 3, is_superuser: false, role: "agent" };
const companyX: ActingAccount = {
  type: "producer",
  userId: 9,
  brandId: 4,
  name: "Company X",
};
const agentOne: ActingAccount = {
  type: "agent",
  userId: 8,
  name: "Agent One",
};

describe("account choice", () => {
  it("sends a superuser to the choose-account screen after login", () => {
    expect(postLoginPath(superuser)).toBe("/choose-account");
    expect(homePath(superuser)).toBe("/choose-account");
    expect(homePath(superuser, "producer")).toBe("/choose-account");
  });

  it("opens the selected company or agent dashboard", () => {
    expect(homePath(superuser, "producer", companyX)).toBe("/brand/studio");
    expect(homePath(superuser, "agent", agentOne)).toBe("/dashboard");
    expect(canAccessBrand(superuser, "producer", companyX)).toBe(true);
    expect(canAccessAgent(superuser, "agent", agentOne)).toBe(true);
    expect(canAccessBrand(superuser, "producer")).toBe(false);
    expect(canAccessBrand(superuser, "agent", agentOne)).toBe(false);
  });

  it("keeps normal accounts on their own dashboard", () => {
    expect(postLoginPath(brandUser)).toBe("/brand/studio");
    expect(postLoginPath(agentUser)).toBe("/dashboard");
    expect(canAccessBrand(brandUser, null)).toBe(true);
    expect(canAccessAgent(agentUser, null)).toBe(true);
  });

  it("only allows internal next paths after login", () => {
    expect(safeNextPath("/brand/studio?from=home")).toBe("/brand/studio?from=home");
    expect(safeNextPath("//evil.com")).toBe(null);
    expect(safeNextPath("https://evil.com")).toBe(null);
    expect(safeNextPath("/login")).toBe("/login");
  });
});
