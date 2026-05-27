"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "Policy Feed", emoji: "📋" },
  { href: "/states", label: "By State", emoji: "🗺️" },
  { href: "/laws", label: "Current Laws", emoji: "⚖️" },
  { href: "/drafts", label: "Content Drafts", emoji: "✍️" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <nav
      style={{
        display: "flex",
        gap: 6,
        background: "#f1f5f9",
        borderRadius: 14,
        padding: 5,
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
              padding: "9px 16px",
              fontSize: 13,
              color: active ? "#fff" : "var(--color-text-muted)",
              fontWeight: 700,
              background: active
                ? "linear-gradient(135deg, #7c3aed 0%, #ec4899 100%)"
                : "transparent",
              borderRadius: 10,
              textDecoration: "none",
              transition: "all 180ms ease",
              display: "flex",
              alignItems: "center",
              gap: 6,
              whiteSpace: "nowrap",
              boxShadow: active ? "0 4px 14px rgba(124, 58, 237, 0.35)" : "none",
            }}
          >
            <span style={{ fontSize: 15 }}>{item.emoji}</span>
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
