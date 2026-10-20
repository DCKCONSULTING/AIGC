import Link from "next/link";

import { MisaLogo } from "@/components/home/MisaLogo";

export function SiteFooter() {
  return (
    <footer className="public-footer">
      <Link href="/" aria-label="MiSa home">
        <MisaLogo variant="word-tag" />
      </Link>
      <p>Agents create product videos. Brands get more reach. Everyone earns.</p>
      <div className="flex flex-wrap gap-5">
        <Link href="/login" className="text-link">
          Agent log in
        </Link>
        <Link href="/register" className="text-link">
          Join as agent
        </Link>
        <Link href="/brand/login" className="text-link">
          Brand log in
        </Link>
        <Link href="/brand/register" className="text-link">
          Join as brand
        </Link>
      </div>
    </footer>
  );
}
