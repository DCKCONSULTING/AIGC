import type { Account, ActingAccount, Role } from "./api";

export function homePath(
  user: Account | null | undefined,
  workspace?: Role | null,
  acting?: ActingAccount | null,
) {
  if (user?.is_superuser) {
    if (workspace === "producer" && acting?.type === "producer" && acting.brandId) {
      return "/brand/studio";
    }
    if (workspace === "agent" && acting?.type === "agent" && acting.userId) {
      return "/dashboard";
    }
    return "/choose-account";
  }
  if (user?.role === "producer") return "/brand/studio";
  return "/dashboard";
}

export function postLoginPath(user: Account) {
  if (user.is_superuser) return "/choose-account";
  return homePath(user);
}

export function loginPath(role: Role) {
  return role === "producer" ? "/brand/login" : "/login";
}

export function registerPath(role: Role) {
  return role === "producer" ? "/brand/register" : "/register";
}

export function safeNextPath(value: string | null | undefined): string | null {
  if (!value) return null;
  if (!value.startsWith("/") || value.startsWith("//") || value.includes("://")) return null;
  if (value.includes("\\") || value.includes("\n") || value.includes("\r")) return null;
  return value;
}

export function canAccessBrand(
  user: Account | null | undefined,
  workspace?: Role | null,
  acting?: ActingAccount | null,
) {
  if (!user) return false;
  if (user.is_superuser) {
    return workspace === "producer" && acting?.type === "producer" && Boolean(acting.brandId);
  }
  return user.role === "producer";
}

export function canAccessAgent(
  user: Account | null | undefined,
  workspace?: Role | null,
  acting?: ActingAccount | null,
) {
  if (!user) return false;
  if (user.is_superuser) {
    return workspace === "agent" && acting?.type === "agent" && Boolean(acting.userId);
  }
  return user.role === "agent";
}
