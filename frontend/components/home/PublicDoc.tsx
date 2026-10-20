import type { Metadata } from "next";
import type { ReactNode } from "react";
import Link from "next/link";

import { PublicFooter } from "@/components/home/PublicFooter";
import { PublicHeader } from "@/components/home/PublicHeader";

export function PublicDoc({
  title,
  lead,
  children,
}: {
  title: string;
  lead: string;
  children: ReactNode;
}) {
  return (
    <div className="misa flex min-h-full flex-1 flex-col">
      <PublicHeader />
      <main className="app-width flex-1 py-16">
        <p className="public-kicker">
          <Link href="/" className="hover:underline">
            MiSa
          </Link>
        </p>
        <h1 className="misa-display mt-3 w-full text-4xl sm:text-5xl">{title}</h1>
        <p className="mt-4 w-full text-lg leading-8 text-muted">{lead}</p>
        <div className="mt-10 w-full space-y-5 leading-7 text-[var(--misa-copy)]">{children}</div>
      </main>
      <PublicFooter />
    </div>
  );
}

export const publicDocMetadata = (title: string, description: string): Metadata => ({
  title,
  description,
});
