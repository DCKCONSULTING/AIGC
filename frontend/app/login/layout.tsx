import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Agent log in",
};

export default function LoginLayout({ children }: LayoutProps<"/login">) {
  return children;
}
