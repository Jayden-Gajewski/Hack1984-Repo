import type { Metadata } from "next";

// Titles the account page (a client page).
export const metadata: Metadata = {
  title: "Account",
  description: "Your Dossier account on this laptop: password and, for admins, local accounts.",
};

export default function AccountLayout({ children }: { children: React.ReactNode }) {
  return children;
}
