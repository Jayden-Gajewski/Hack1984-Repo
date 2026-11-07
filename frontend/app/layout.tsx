import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Hack1984",
  description:
    "Find where your personal data is exposed, and see exactly what left your laptop.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
