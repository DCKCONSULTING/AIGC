import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Join as an agent",
};

export default function RegisterLayout({ children }: LayoutProps<"/register">) {
  return children;
}
