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

export default function Dashboard() {
  const [items, setItems] = useState<PolicyItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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
  }, [filters]);

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
          <Filters filters={filters} onChange={setFilters} />

          <div style={{ fontSize: 12, color: "var(--color-text-subtle)", fontWeight: 600 }}>
            {loading ? "Loading..." : `${total} item${total !== 1 ? "s" : ""}`}
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
