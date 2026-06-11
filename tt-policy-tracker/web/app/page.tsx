"use client";

import { useEffect, useState } from "react";
import { AdminControls } from "./components/AdminControls";
import { Filters } from "./components/Filters";
import { Header } from "./components/Header";
import { Nav } from "./components/Nav";
import { PolicyItemCard } from "./components/PolicyItemCard";
import { StatsBar } from "./components/StatsBar";

interface PolicyItem {
  id: number;
  title: string;
  summary: string;
  impact_score: "low" | "med" | "high";
  impact_reasoning: string | null;
  action_needed: string | null;
  topics: string[] | null;
  source_url: string | null;
  effective_date: string | null;
  published_at: string | null;
  discovered_at: string | null;
  jurisdiction_id: number | null;
}

interface ApiResponse {
  total: number;
  offset: number;
  limit: number;
  items: PolicyItem[];
}

type TabKey = "act" | "monitor" | "fyi" | "all";

const TABS: { key: TabKey; label: string; emoji: string; action_needed?: string; description: string }[] = [
  {
    key: "act",
    label: "Act Now",
    emoji: "⚡",
    action_needed: "urgent",
    description: "Enacted or imminent laws to handle in the next few months.",
  },
  {
    key: "monitor",
    label: "Monitor",
    emoji: "👀",
    action_needed: "monitor",
    description: "Active bills worth watching as they move.",
  },
  {
    key: "fyi",
    label: "FYI",
    emoji: "🗂️",
    action_needed: "inform",
    description: "Dead, postponed, or niche — skim and move on.",
  },
  { key: "all", label: "Everything", emoji: "📋", description: "All tracked items, de-duped." },
];

export default function Dashboard() {
  const [items, setItems] = useState<PolicyItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("act");
  const [filters, setFilters] = useState<{
    topic?: string;
    impact?: string;
    state?: string;
  }>({});

  useEffect(() => {
    const params = new URLSearchParams();
    if (filters.topic) params.set("topic", filters.topic);
    if (filters.impact) params.set("impact", filters.impact);
    if (filters.state) params.set("state", filters.state);
    const activeTab = TABS.find((t) => t.key === tab);
    if (activeTab?.action_needed) params.set("action_needed", activeTab.action_needed);
    params.set("limit", "50");

    setLoading(true);
    setError(null);
    fetch(`/api/items?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`API returned ${r.status}`);
        return r.json();
      })
      .then((data: ApiResponse) => {
        setItems(data.items || []);
        setTotal(data.total || 0);
      })
      .catch((err) => {
        console.error("Failed to fetch items:", err);
        setError("Could not connect to the API. Check that NEXT_PUBLIC_API_URL is configured.");
        setItems([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, [filters, tab]);

  const activeTab = TABS.find((t) => t.key === tab) || TABS[0];

  return (
    <div>
      <Header subtitle="She reads every rental housing law in America so you don't have to." />

      <main
        className="page-fade-in"
        style={{
          maxWidth: 1000,
          margin: "0 auto",
          padding: "0 24px 48px",
          position: "relative",
          zIndex: 2,
        }}
      >
        <div
          className="card"
          style={{
            padding: "20px 24px",
            marginBottom: 20,
            boxShadow: "var(--shadow-lg)",
          }}
        >
          <Nav />
          <StatsBar />

          {/* Status tabs: New Laws vs To Monitor vs Everything */}
          <div
            role="tablist"
            style={{
              display: "flex",
              gap: 4,
              background: "#f1f5f9",
              borderRadius: 12,
              padding: 4,
              width: "fit-content",
              marginBottom: 12,
            }}
          >
            {TABS.map((t) => {
              const active = t.key === tab;
              return (
                <button
                  key={t.key}
                  role="tab"
                  aria-selected={active}
                  onClick={() => setTab(t.key)}
                  style={{
                    padding: "7px 14px",
                    fontSize: 12,
                    fontWeight: 700,
                    color: active ? "#fff" : "var(--color-text-muted)",
                    background: active
                      ? "linear-gradient(135deg, #7c3aed 0%, #ec4899 100%)"
                      : "transparent",
                    border: "none",
                    borderRadius: 8,
                    cursor: "pointer",
                    transition: "all 160ms ease",
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    whiteSpace: "nowrap",
                    boxShadow: active ? "0 3px 12px rgba(124, 58, 237, 0.3)" : "none",
                  }}
                >
                  <span style={{ fontSize: 13 }}>{t.emoji}</span>
                  {t.label}
                </button>
              );
            })}
          </div>

          <Filters filters={filters} onChange={setFilters} />

          <div style={{ fontSize: 12, color: "var(--color-text-subtle)", fontWeight: 600 }}>
            {loading
              ? "Loading..."
              : `${total} ${activeTab.label.toLowerCase()} item${total !== 1 ? "s" : ""} · ${activeTab.description}`}
          </div>
        </div>

        {error && (
          <div
            className="card"
            style={{
              background: "#fef2f2",
              borderColor: "#fecaca",
              padding: "14px 18px",
              color: "#991b1b",
              fontSize: 13,
              marginBottom: 16,
            }}
          >
            {error}
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map((item) => (
            <PolicyItemCard key={item.id} item={item} />
          ))}
        </div>

        {!loading && !error && items.length === 0 && (
          <div
            className="card"
            style={{
              textAlign: "center",
              padding: 56,
              color: "var(--color-text-subtle)",
            }}
          >
            <div style={{ fontSize: 48, marginBottom: 12 }}>🕵️‍♀️</div>
            <div style={{ fontSize: 17, color: "var(--color-text)", fontWeight: 700, marginBottom: 6, letterSpacing: "-0.01em" }}>
              Nothing in the feed yet
            </div>
            <div style={{ fontSize: 13, lineHeight: 1.5 }}>
              Jeanne&apos;s ready to read. Hit the <strong>Admin</strong> button (bottom-right) to kick off her first run.
            </div>
          </div>
        )}
      </main>

      <AdminControls />
    </div>
  );
}
