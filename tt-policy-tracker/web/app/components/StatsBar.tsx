"use client";

import { useEffect, useState } from "react";

interface Stats {
  total_items: number;
  high_impact_items: number;
  total_jurisdictions: number;
}

export function StatsBar() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    fetch("/api/stats")
      .then((r) => r.json())
      .then(setStats)
      .catch(() => {});
  }, []);

  if (!stats) return null;

  const cards = [
    { label: "Total Items", value: stats.total_items, color: "#1a56db" },
    { label: "High Impact", value: stats.high_impact_items, color: "#dc2626" },
    { label: "Jurisdictions", value: stats.total_jurisdictions, color: "#059669" },
  ];

  return (
    <div style={{ display: "flex", gap: 12, marginBottom: 20 }}>
      {cards.map((card) => (
        <div
          key={card.label}
          style={{
            flex: 1,
            background: "#fff",
            borderRadius: 8,
            padding: "16px 20px",
            boxShadow: "0 1px 3px rgba(0,0,0,0.08)",
          }}
        >
          <div style={{ fontSize: 28, fontWeight: 700, color: card.color }}>
            {card.value}
          </div>
          <div style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>
            {card.label}
          </div>
        </div>
      ))}
    </div>
  );
}
