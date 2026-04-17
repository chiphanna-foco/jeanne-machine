import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Jeanne Machine",
  description: "She reads every rental housing law in America so you don't have to.",
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
