"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { MisaLogo } from "@/components/home/MisaLogo";
import { useAuth } from "@/lib/auth";
import { canAccessBrand, homePath, loginPath } from "@/lib/paths";

import { BrandSidebar } from "./BrandSidebar";

export function BrandWorkspace({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, ready, workspace, actingAccount } = useAuth();
  const [open, setOpen] = useState(false);
  const allowed = canAccessBrand(user, workspace, actingAccount);
  const studio = pathname === "/brand/studio" || pathname.startsWith("/brand/studio/");

  useEffect(() => {
    if (ready && !user) {
      router.replace(loginPath("producer"));
    } else if (ready && user && !allowed) {
      router.replace(homePath(user, workspace, actingAccount));
    }
  }, [ready, user, workspace, actingAccount, allowed, router]);

  if (!ready || !user || !allowed) {
    return (
      <div className="flex min-h-full flex-1 items-center justify-center text-muted">
        Loading…
      </div>
    );
  }

  return (
    <div className="workspace-shell flex min-h-full flex-1">
      <div className="hidden md:block">
        <div className="sticky top-0 h-screen">
          <BrandSidebar />
        </div>
      </div>

      {open ? (
        <div className="fixed inset-0 z-40 md:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-[#09132f]/30"
            aria-label="Close menu"
            onClick={() => setOpen(false)}
          />
          <div className="relative h-full w-64">
            <BrandSidebar onNavigate={() => setOpen(false)} />
          </div>
        </div>
      ) : null}

      <div className="workspace-canvas flex min-w-0 flex-1 flex-col">
        <div className="border-b border-[rgba(219,228,241,0.9)] bg-white/88 py-3 backdrop-blur-md md:hidden">
          <div className="flex items-center justify-between px-4">
            <Link href="/brand/studio" className="block" aria-label="MiSa Studio">
              <MisaLogo variant="word" className="compact" />
            </Link>
            <button
              type="button"
              className="rounded-[11px] border border-[#d8e1ee] bg-white px-3 py-1.5 text-sm"
              onClick={() => setOpen(true)}
            >
              Menu
            </button>
          </div>
        </div>
        <main
          className={
            studio
              ? "relative z-[1] min-w-0 flex-1 px-4 py-5 md:px-6 lg:px-8"
              : "app-width relative z-[1] flex-1 py-8"
          }
        >
          {children}
        </main>
      </div>
    </div>
  );
}
