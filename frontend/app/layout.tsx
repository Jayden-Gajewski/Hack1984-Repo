import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Dossier",
  description:
    "Find where your personal data is exposed, and see exactly what left your laptop.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Browser extensions add attributes to <html> before React loads; ignore those mismatches here only.
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
