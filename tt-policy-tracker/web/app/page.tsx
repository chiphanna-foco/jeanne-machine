"use client";

import { useEffect, useState } from "react";
import { Filters } from "./components/Filters";
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

const API_BASE = "/api";

export default function Dashboard() {
  const [items, setItems] = useState<PolicyItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
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
    fetch(`${API_BASE}/items?${params}`)
      .then((r) => r.json())
      .then((data: ApiResponse) => {
        setItems(data.items);
        setTotal(data.total);
      })
      .catch((err) => console.error("Failed to fetch items:", err))
      .finally(() => setLoading(false));
  }, [filters]);

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "24px 16px" }}>
      <header style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: "#1a56db", margin: 0 }}>
          TT Policy Tracker
        </h1>
        <p style={{ color: "#6b7280", fontSize: 14, margin: "4px 0 0 0" }}>
          Internal legislative monitoring dashboard
        </p>
      </header>

      <StatsBar />

      <Filters filters={filters} onChange={setFilters} />

      <div style={{ marginBottom: 12, fontSize: 13, color: "#6b7280" }}>
        {loading ? "Loading..." : `${total} item${total !== 1 ? "s" : ""}`}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {items.map((item) => (
          <PolicyItemCard key={item.id} item={item} />
        ))}
      </div>

      {!loading && items.length === 0 && (
        <div
          style={{
            textAlign: "center",
            padding: 48,
            color: "#9ca3af",
          }}
        >
          No policy items found. Run the ingestion and enrichment pipelines to populate data.
        </div>
      )}
    </div>
  );
}
