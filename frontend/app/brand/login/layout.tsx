import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Brand log in",
};

export default function BrandLoginLayout({
  children,
}: LayoutProps<"/brand/login">) {
  return children;
}
