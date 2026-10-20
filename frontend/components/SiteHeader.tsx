"use client";

import Link from "next/link";
import { useState } from "react";

import { MisaLogo } from "@/components/home/MisaLogo";
import { useAuth } from "@/lib/auth";
import { homePath } from "@/lib/paths";

export function SiteHeader() {
  const { user, ready, workspace, actingAccount } = useAuth();
  const [open, setOpen] = useState(false);
  const studioLabel = user?.is_superuser
    ? actingAccount?.type === "producer"
      ? actingAccount.name
      : actingAccount?.type === "agent"
        ? actingAccount.name
        : "Choose account"
    : user?.role === "producer"
      ? "Brand studio"
      : "Dashboard";

  return (
    <header className={`public-header ${open ? "is-open" : ""}`}>
      <div className="public-header-bar">
      <Link href="/" className="shrink-0" aria-label="MiSa home">
        <MisaLogo variant="word-tag" />
      </Link>

      <nav className="public-links" aria-label="Account navigation">
        <a href="/#how">How it works</a>
        <a href="/#examples">Examples</a>
        <a href="/#pricing">Pricing</a>
      </nav>

      <div className="public-actions">
        {!ready ? null : user ? (
          <Link
            href={homePath(user, workspace, actingAccount)}
            className="public-create inline-flex items-center justify-center"
          >
            {studioLabel}
          </Link>
        ) : (
          <>
            <Link href="/brand/login" className="public-signin">
              Sign in
            </Link>
            <Link href="/brand/register" className="public-create inline-flex items-center justify-center">
              Create account
            </Link>
          </>
        )}
        <button
          type="button"
          className="public-menu-button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-label="Toggle menu"
        >
          {open ? "×" : "☰"}
        </button>
      </div>
      </div>

      <div className="public-mobile-panel">
        <div className="flex flex-col gap-4 px-5 text-sm">
          <a href="/#how" onClick={() => setOpen(false)}>
            How it works
          </a>
          <a href="/#examples" onClick={() => setOpen(false)}>
            Examples
          </a>
          <a href="/#pricing" onClick={() => setOpen(false)}>
            Pricing
          </a>
          {!ready ? null : user ? (
            <Link href={homePath(user, workspace, actingAccount)} onClick={() => setOpen(false)}>
              {studioLabel}
            </Link>
          ) : (
            <>
              <Link href="/brand/login" onClick={() => setOpen(false)}>
                Brand log in
              </Link>
              <Link href="/login" onClick={() => setOpen(false)}>
                Agent log in
              </Link>
              <Link href="/brand/register" onClick={() => setOpen(false)}>
                Join as brand
              </Link>
              <Link href="/register" onClick={() => setOpen(false)}>
                Join as agent
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
