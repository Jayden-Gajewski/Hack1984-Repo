import type { Metadata } from "next";

// Titles the account page (a client page).
export const metadata: Metadata = {
  title: "Account",
  description: "Your Dossier account: password and, for admins, every account.",
};

export default function AccountLayout({ children }: { children: React.ReactNode }) {
  return children;
}
