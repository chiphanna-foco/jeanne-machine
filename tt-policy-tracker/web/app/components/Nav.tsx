"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "Policy Items" },
  { href: "/laws", label: "Current Laws" },
  { href: "/drafts", label: "Content Drafts" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <nav
      style={{
        display: "flex",
        gap: 4,
        marginBottom: 24,
        borderBottom: "1px solid #e5e7eb",
      }}
    >
      {NAV_ITEMS.map((item) => {
        const active = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            style={{
              padding: "10px 16px",
              fontSize: 14,
              color: active ? "#1a56db" : "#6b7280",
              fontWeight: active ? 600 : 500,
              borderBottom: active ? "2px solid #1a56db" : "2px solid transparent",
              textDecoration: "none",
              marginBottom: -1,
            }}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
