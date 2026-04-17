import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Jeanne Machine",
  description: "Rental housing policy intelligence — federal, state, and local legislation tracked, summarized, and delivered.",
  icons: {
    icon: "/logo.svg",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
