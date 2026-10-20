import type { Metadata } from "next";

import { AgentWorkspace } from "@/components/agent/AgentWorkspace";

export const metadata: Metadata = {
  title: "Agent workspace",
};

export default function DashboardLayout({ children }: LayoutProps<"/dashboard">) {
  return <AgentWorkspace>{children}</AgentWorkspace>;
}
