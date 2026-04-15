import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "TT Policy Tracker",
  description: "TurboTenant Legislative Policy Tracker — Internal Dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif", backgroundColor: "#f8fafc", color: "#1a1a1a" }}>
        {children}
      </body>
    </html>
  );
}
