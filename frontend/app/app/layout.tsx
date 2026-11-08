import type { Metadata } from "next";

// Titles the signed-in scanner. The page itself is a client component, which can't export metadata.
export const metadata: Metadata = {
  title: "Exposure scan",
  description: "Where your personal data is exposed, the likely source of each listing, and the opt-out requests.",
};

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return children;
}
