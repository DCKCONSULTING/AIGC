import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Register your brand",
};

export default function BrandRegisterLayout({
  children,
}: LayoutProps<"/brand/register">) {
  return children;
}
