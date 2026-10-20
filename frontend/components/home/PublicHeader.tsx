"use client";

import Link from "next/link";
import { useState } from "react";

import { MisaLogo } from "./MisaLogo";

const links = [
  { href: "/#how", label: "How it works" },
  { href: "/#examples", label: "Examples" },
  { href: "/#pricing", label: "Pricing" },
];

export function PublicHeader({
  onCreate,
}: {
  onCreate?: () => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <header className={`public-header ${open ? "is-open" : ""}`}>
      <div className="public-header-bar">
      <Link href="/" className="shrink-0" aria-label="MiSa home">
        <MisaLogo variant="word-tag" priority />
      </Link>

      <nav className="public-links" aria-label="Public navigation">
        {links.map((link) => (
          <a key={link.href} href={link.href}>
            {link.label}
          </a>
        ))}
      </nav>

      <div className="public-actions">
        <Link href="/brand/login" className="public-signin">
          Sign in
        </Link>
        <Link
          href="/#free-trial"
          onClick={onCreate}
          className="public-create inline-flex items-center justify-center"
        >
          Try 15 sec free
        </Link>
        <button
          type="button"
          className="public-menu-button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-label={open ? "Close menu" : "Open menu"}
        >
          {open ? "×" : "☰"}
        </button>
      </div>
      </div>

      <div className="public-mobile-panel">
        <div className="flex flex-col gap-4 px-5 text-sm">
          {links.map((link) => (
            <a key={link.href} href={link.href} onClick={() => setOpen(false)}>
              {link.label}
            </a>
          ))}
          <Link href="/brand/login" onClick={() => setOpen(false)}>
            Sign in
          </Link>
          <Link
            href="/#free-trial"
            onClick={() => {
              onCreate?.();
              setOpen(false);
            }}
            className="public-create inline-flex items-center justify-center"
          >
            Try 15 sec free
          </Link>
        </div>
      </div>
    </header>
  );
}
