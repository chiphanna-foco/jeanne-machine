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
    gradient: "linear-gradient(135deg, #7c3aed 0%, #a855f7 100%)",
    glow: "rgba(168, 85, 247, 0.35)",
    emoji: "📋",
  },
  {
    key: "high_impact_items" as const,
    label: "High Impact",
    sublabel: "Eyes up",
    gradient: "linear-gradient(135deg, #ec4899 0%, #f59e0b 100%)",
    glow: "rgba(236, 72, 153, 0.35)",
    emoji: "🚨",
  },
  {
    key: "total_jurisdictions" as const,
    label: "Jurisdictions",
    sublabel: "Coast to coast",
    gradient: "linear-gradient(135deg, #06b6d4 0%, #0ea5e9 100%)",
    glow: "rgba(6, 182, 212, 0.35)",
    emoji: "🗺️",
  },
];

function useCountUp(target: number, duration = 900) {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (!target) {
      setValue(0);
      return;
    }
    let start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const elapsed = now - start;
      const t = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(Math.round(target * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return value;
}

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
        gap: 14,
        marginBottom: 24,
      }}
    >
      {CARDS.map((card) => (
        <StatCard key={card.key} card={card} value={stats[card.key]} />
      ))}
    </div>
  );
}

function StatCard({
  card,
  value,
}: {
  card: (typeof CARDS)[number];
  value: number;
}) {
  const display = useCountUp(value);
  return (
    <div
      style={{
        position: "relative",
        overflow: "hidden",
        padding: "20px 22px",
        borderRadius: 14,
        background: "#fff",
        border: "1px solid var(--color-border)",
        boxShadow: "var(--shadow-sm)",
        transition: "transform 220ms ease, box-shadow 220ms ease",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = "translateY(-3px)";
        e.currentTarget.style.boxShadow = `0 12px 30px ${card.glow}`;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = "translateY(0)";
        e.currentTarget.style.boxShadow = "var(--shadow-sm)";
      }}
    >
      {/* Accent gradient strip */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 4,
          background: card.gradient,
        }}
      />

      {/* Background emoji */}
      <div
        style={{
          position: "absolute",
          top: 10,
          right: 14,
          fontSize: 36,
          opacity: 0.12,
          filter: "grayscale(0.2)",
          pointerEvents: "none",
        }}
      >
        {card.emoji}
      </div>

      <div
        style={{
          fontSize: 36,
          fontWeight: 900,
          lineHeight: 1,
          letterSpacing: "-0.04em",
          background: card.gradient,
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
          marginTop: 10,
        }}
      >
        {display.toLocaleString()}
      </div>
      <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text)", marginTop: 6 }}>
        {card.label}
      </div>
      <div style={{ fontSize: 11, color: "var(--color-text-subtle)", marginTop: 2, fontWeight: 500 }}>
        {card.sublabel}
      </div>
    </div>
  );
}
