"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { MisaLogo } from "@/components/home/MisaLogo";
import { AGENT_NAV, isAgentNavActive } from "@/lib/agent";
import { useAuth } from "@/lib/auth";

export function AgentSidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, actingAccount, logout, clearActingAccount } = useAuth();
  const initials = (actingAccount?.name || user?.name || "AG")
    .split(" ")
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <aside className="workspace-sidebar flex h-full w-64 flex-col px-3 py-5">
      <div className="px-2 pb-4">
        <Link href="/dashboard" className="block" onClick={onNavigate} aria-label="MiSa Agent">
          <MisaLogo variant="word-tag" className="compact" />
        </Link>
        <p className="mt-3 px-1 text-[9px] font-extrabold uppercase tracking-[0.16em] text-[#9aa5ba]">
          Agent workspace
        </p>
      </div>

      <nav className="flex flex-1 flex-col gap-0.5">
        <p className="mb-1 mt-2 px-3 text-[9px] font-extrabold uppercase tracking-[0.16em] text-[#9aa5ba]">
          Distribute
        </p>
        {AGENT_NAV.map((link) => {
          const active = isAgentNavActive(pathname, link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              onClick={onNavigate}
              className={`workspace-nav-item flex items-center gap-3 ${active ? "active" : ""}`}
            >
              <span>{link.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto border-t border-[#e7eef8] pt-3">
        <div className="grid grid-cols-[auto_1fr] items-center gap-2.5 px-2 py-2">
          <span className="grid h-8 w-8 place-items-center rounded-[10px] bg-[linear-gradient(135deg,var(--misa-blue),var(--misa-violet))] text-[11px] font-bold text-white">
            {initials}
          </span>
          <span className="min-w-0">
            <strong className="block truncate text-xs text-[var(--misa-navy)]">
              {actingAccount?.name || user?.name}
            </strong>
            <small className="block truncate text-[11px] text-[#526078]">
              {actingAccount?.subtitle || user?.email}
            </small>
          </span>
        </div>
        {user?.is_superuser ? (
          <Link
            href="/choose-account"
            onClick={() => {
              clearActingAccount();
              onNavigate?.();
            }}
            className="mt-2 block w-full rounded-[13px] border border-[#d8e1ee] px-4 py-2 text-center text-sm hover:bg-[#f1f8ff]"
          >
            Switch account
          </Link>
        ) : null}
        <button
          type="button"
          onClick={() => logout().then(() => router.push("/"))}
          className="mt-2 w-full rounded-[13px] border border-[#d8e1ee] px-4 py-2 text-sm hover:bg-[#f1f8ff]"
        >
          Logout
        </button>
      </div>
    </aside>
  );
}
