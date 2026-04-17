"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "Policy Feed", icon: "📋" },
  { href: "/laws", label: "Current Laws", icon: "⚖️" },
  { href: "/drafts", label: "Content Drafts", icon: "✍️" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <nav
      style={{
        display: "flex",
        gap: 4,
        background: "#fff",
        borderRadius: 12,
        padding: 4,
        border: "1px solid var(--color-border)",
        boxShadow: "var(--shadow-sm)",
        width: "fit-content",
        marginBottom: 24,
      }}
    >
      {NAV_ITEMS.map((item) => {
        const active = pathname === item.href;
        return (
          <Link
            key={item.href}
            href={item.href}
            style={{
              padding: "8px 14px",
              fontSize: 13,
              color: active ? "#fff" : "var(--color-text-muted)",
              fontWeight: 600,
              background: active ? "var(--color-primary)" : "transparent",
              borderRadius: 8,
              textDecoration: "none",
              transition: "all 160ms ease",
              display: "flex",
              alignItems: "center",
              gap: 6,
              whiteSpace: "nowrap",
            }}
          >
            <span style={{ fontSize: 14 }}>{item.icon}</span>
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
