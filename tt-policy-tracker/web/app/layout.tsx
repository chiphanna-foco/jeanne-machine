import type { Metadata } from "next";
import { SiteFooter } from "./components/SiteFooter";
import { UserBar } from "./components/UserBar";
import "./globals.css";

export const metadata: Metadata = {
  title: "Jeanne Machine",
  description: "She reads every rental housing law in America so you don't have to.",
};

// Access is enforced by middleware.ts (Google sign-in, turbotenant.com only).
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body style={{ position: "relative" }}>
        <UserBar />
        {children}
        <SiteFooter />
      </body>
    </html>
  );
}
