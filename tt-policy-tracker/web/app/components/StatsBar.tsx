"use client";

import { useEffect, useState } from "react";

interface Stats {
  total_items: number;
  high_impact_items: number;
  total_jurisdictions: number;
}

const CARDS = [
  {
    key: "total_items" as const,
    label: "Policy Items",
    sublabel: "AI-analyzed",
    accent: "#1e3a8a",
    iconBg: "rgba(30, 58, 138, 0.08)",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
        <path d="M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" stroke="currentColor" strokeWidth="1.6"/>
        <path d="M9 8h6M9 12h6M9 16h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
      </svg>
    ),
  },
  {
    key: "high_impact_items" as const,
    label: "High Impact",
    sublabel: "Urgent attention",
    accent: "#dc2626",
    iconBg: "rgba(220, 38, 38, 0.08)",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
        <path d="M12 2 3 22h18L12 2z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"/>
        <path d="M12 9v6M12 18h.01" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
      </svg>
    ),
  },
  {
    key: "total_jurisdictions" as const,
    label: "Jurisdictions",
    sublabel: "Federal + state + local",
    accent: "#059669",
    iconBg: "rgba(5, 150, 105, 0.08)",
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.6"/>
        <path d="M3 12h18M12 3a12 12 0 0 1 0 18M12 3a12 12 0 0 0 0 18" stroke="currentColor" strokeWidth="1.6"/>
      </svg>
    ),
  },
];

export function StatsBar() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    fetch("/api/stats")
      .then((r) => {
        if (!r.ok) throw new Error(`API returned ${r.status}`);
        return r.json();
      })
      .then(setStats)
      .catch(() => setStats(null));
  }, []);

  if (!stats) return null;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        gap: 12,
        marginBottom: 24,
      }}
    >
      {CARDS.map((card) => (
        <div
          key={card.key}
          className="card"
          style={{
            padding: "18px 20px",
            display: "flex",
            alignItems: "center",
            gap: 14,
          }}
        >
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: 10,
              background: card.iconBg,
              color: card.accent,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            {card.icon}
          </div>
          <div>
            <div
              style={{
                fontSize: 24,
                fontWeight: 700,
                color: card.accent,
                lineHeight: 1,
                letterSpacing: "-0.03em",
              }}
            >
              {stats[card.key].toLocaleString()}
            </div>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text)", marginTop: 4 }}>
              {card.label}
            </div>
            <div style={{ fontSize: 11, color: "var(--color-text-subtle)", marginTop: 1 }}>
              {card.sublabel}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
