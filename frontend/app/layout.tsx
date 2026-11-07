import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import "./site.css";

// Self-hosted Geist (SIL Open Font License, see fonts/OFL.txt): pages never fetch fonts.
const sans = localFont({ src: "./fonts/Geist-Variable.woff2", variable: "--font-sans", weight: "100 900" });
const mono = localFont({ src: "./fonts/GeistMono-Variable.woff2", variable: "--font-mono", weight: "100 900" });

export const metadata: Metadata = {
  title: "Dossier",
  description:
    "Find where your personal data is exposed, and see exactly what left your laptop.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Browser extensions add attributes to <html> before React loads; ignore those mismatches here only.
    <html lang="en" data-theme="dark" suppressHydrationWarning className={`${sans.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
