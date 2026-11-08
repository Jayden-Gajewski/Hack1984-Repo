import type { Metadata } from "next";

// Titles the threat monitor (a client page).
export const metadata: Metadata = {
  title: "Threat monitor",
  description: "Known data breaches at the companies you use, and what to do about each one.",
};

export default function MonitorLayout({ children }: { children: React.ReactNode }) {
  return children;
}
