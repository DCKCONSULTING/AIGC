"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  ACTING_STORAGE_KEY,
  api,
  endpoints,
  type Account,
  type ActingAccount,
  type AgentRegisterPayload,
  type AuthResponse,
  type BrandOwnerProfile,
  type BrandRegisterPayload,
  type Role,
} from "./api";

const TOKEN_KEY = "dckbrand.token";
const WORKSPACE_KEY = "dckbrand.workspace";

type AuthContextValue = {
  user: Account | null;
  token: string | null;
  workspace: Role | null;
  actingAccount: ActingAccount | null;
  ready: boolean;
  login: (identifier: string, password: string, role: Role) => Promise<Account>;
  register: (payload: AgentRegisterPayload) => Promise<void>;
  registerBrand: (payload: BrandRegisterPayload) => Promise<void>;
  chooseAccount: (account: ActingAccount) => void;
  clearActingAccount: () => void;
  logout: () => Promise<void>;
  applyProfile: (profile: BrandOwnerProfile | Account) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function readWorkspace(): Role | null {
  if (typeof window === "undefined") return null;
  const stored = localStorage.getItem(WORKSPACE_KEY);
  if (stored === "agent" || stored === "producer") return stored;
  return null;
}

function readActing(): ActingAccount | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(ACTING_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ActingAccount;
    if (!parsed?.userId || (parsed.type !== "agent" && parsed.type !== "producer")) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<Account | null>(null);
  const [workspace, setWorkspace] = useState<Role | null>(null);
  const [actingAccount, setActingAccount] = useState<ActingAccount | null>(null);
  const [ready, setReady] = useState(false);

  const applyAuth = useCallback((payload: AuthResponse) => {
    localStorage.setItem(TOKEN_KEY, payload.token);
    setToken(payload.token);
    setUser(payload.user);
  }, []);

  useEffect(() => {
    setWorkspace(readWorkspace());
    setActingAccount(readActing());
    const stored = localStorage.getItem(TOKEN_KEY);
    if (!stored) {
      setReady(true);
      return;
    }

    api<Account>(endpoints.auth.me, { token: stored })
      .then((profile) => {
        setToken(stored);
        setUser(profile);
      })
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
      })
      .finally(() => setReady(true));
  }, []);

  const clearActingAccount = useCallback(() => {
    localStorage.removeItem(WORKSPACE_KEY);
    localStorage.removeItem(ACTING_STORAGE_KEY);
    setWorkspace(null);
    setActingAccount(null);
  }, []);

  const login = useCallback(
    async (identifier: string, password: string, role: Role) => {
      const path =
        role === "producer" ? endpoints.brands.login : endpoints.agents.login;
      const payload = await api<AuthResponse>(path, {
        method: "POST",
        body: JSON.stringify({ identifier, password }),
      });
      if (payload.user.is_superuser) {
        localStorage.removeItem(WORKSPACE_KEY);
        localStorage.removeItem(ACTING_STORAGE_KEY);
        setWorkspace(null);
        setActingAccount(null);
      }
      applyAuth(payload);
      return payload.user;
    },
    [applyAuth],
  );

  const register = useCallback(
    async (form: AgentRegisterPayload) => {
      const payload = await api<AuthResponse>(endpoints.agents.register, {
        method: "POST",
        body: JSON.stringify(form),
      });
      applyAuth(payload);
    },
    [applyAuth],
  );

  const registerBrand = useCallback(
    async (form: BrandRegisterPayload) => {
      const payload = await api<AuthResponse>(endpoints.brands.register, {
        method: "POST",
        body: JSON.stringify(form),
      });
      applyAuth(payload);
    },
    [applyAuth],
  );

  const chooseAccount = useCallback((account: ActingAccount) => {
    localStorage.setItem(WORKSPACE_KEY, account.type);
    localStorage.setItem(ACTING_STORAGE_KEY, JSON.stringify(account));
    setWorkspace(account.type);
    setActingAccount(account);
  }, []);

  const logout = useCallback(async () => {
    if (token) {
      try {
        await api(endpoints.auth.logout, { method: "POST", token });
      } catch {
        // Token may already be invalid; still clear the local session.
      }
    }
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(WORKSPACE_KEY);
    localStorage.removeItem(ACTING_STORAGE_KEY);
    setToken(null);
    setUser(null);
    setWorkspace(null);
    setActingAccount(null);
  }, [token]);

  const applyProfile = useCallback((profile: BrandOwnerProfile | Account) => {
    setUser((current) => {
      if (!current || current.id !== profile.id) return current;
      return {
        ...current,
        username: profile.username,
        name: profile.name,
        email: profile.email,
        mobile: profile.mobile,
        location: profile.location,
      };
    });
    setActingAccount((current) => {
      if (!current || current.userId !== profile.id) return current;
      const company = "company" in profile ? profile.company : null;
      const next = {
        ...current,
        subtitle: profile.name,
        email: profile.email,
        username: profile.username,
        mobile: profile.mobile,
        location: company?.location || profile.location,
        name:
          company && (!current.brandId || current.brandId === company.id)
            ? company.name
            : current.name,
      };
      localStorage.setItem(ACTING_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const value = useMemo(
    () => ({
      user,
      token,
      workspace,
      actingAccount,
      ready,
      login,
      register,
      registerBrand,
      chooseAccount,
      clearActingAccount,
      logout,
      applyProfile,
    }),
    [
      user,
      token,
      workspace,
      actingAccount,
      ready,
      login,
      register,
      registerBrand,
      chooseAccount,
      clearActingAccount,
      logout,
      applyProfile,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
