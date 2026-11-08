import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";
import "./site.css";

// Self-hosted Geist (SIL Open Font License, see fonts/OFL.txt): pages never fetch fonts.
const sans = localFont({ src: "./fonts/Geist-Variable.woff2", variable: "--font-sans", weight: "100 900" });
const mono = localFont({ src: "./fonts/GeistMono-Variable.woff2", variable: "--font-mono", weight: "100 900" });

const DESCRIPTION =
  "Dossier finds your listings on people-search sites, shows the likely source with its evidence, and drafts the opt-out. Every request it sends is logged, including what Gemini reads.";

export const metadata: Metadata = {
  // Absolute URLs (the Open Graph image) use the public site's address when there is one. On
  // Vercel without SITE_URL, the project's production address (a variable Vercel sets) stands in.
  metadataBase: new URL(
    process.env.SITE_URL ??
      (process.env.VERCEL_PROJECT_PRODUCTION_URL
        ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
        : "http://localhost:3000"),
  ),
  title: { default: "Dossier: find where your personal data is exposed", template: "%s | Dossier" },
  description: DESCRIPTION,
  applicationName: "Dossier",
  openGraph: {
    type: "website",
    siteName: "Dossier",
    title: "Dossier: find where your personal data is exposed",
    description: DESCRIPTION,
  },
  twitter: { card: "summary_large_image" },
};

export const viewport: Viewport = {
  themeColor: "#060b1a",
  colorScheme: "dark",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Browser extensions add attributes to <html> before React loads; ignore those mismatches here only.
    <html lang="en" data-theme="dark" suppressHydrationWarning className={`${sans.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
