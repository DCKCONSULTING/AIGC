"use client";

import Link from "next/link";

import { MisaLogo } from "./MisaLogo";

export function PublicFooter({
  locale = "en",
  onLocale,
}: {
  locale?: "en" | "bm";
  onLocale?: (next: "en" | "bm") => void;
}) {
  return (
    <footer className="public-footer">
      <Link href="/" aria-label="MiSa home">
        <MisaLogo variant="word-tag" />
      </Link>
      <p>Made for Malaysian brands. Designed for the way we speak.</p>
      <div className="flex flex-wrap items-center gap-5">
        {onLocale ? (
          <div className="flex gap-3 text-sm">
            <button
              type="button"
              className={locale === "en" ? "text-link" : "text-[#6d7891]"}
              onClick={() => onLocale("en")}
            >
              English
            </button>
            <button
              type="button"
              className={locale === "bm" ? "text-link" : "text-[#6d7891]"}
              onClick={() => onLocale("bm")}
            >
              Bahasa Melayu
            </button>
          </div>
        ) : null}
        <Link href="/help" className="text-link">
          Help centre
        </Link>
        <Link href="/privacy" className="text-link">
          Privacy
        </Link>
        <Link href="/terms" className="text-link">
          Terms
        </Link>
      </div>
    </footer>
  );
}
