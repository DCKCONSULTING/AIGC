import type { Metadata } from "next";

import { BrandWorkspace } from "@/components/brand/BrandWorkspace";

export const metadata: Metadata = {
  title: "MISA Studio",
};

export default function BrandWorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <BrandWorkspace>{children}</BrandWorkspace>;
}
