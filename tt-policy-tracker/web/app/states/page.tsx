"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AdminControls } from "../components/AdminControls";
import { Header } from "../components/Header";
import { Nav } from "../components/Nav";

interface StateRow {
  state_code: string;
  name: string;
  item_count: number;
  law_topic_count: number;
}

export default function StatesPage() {
  const [states, setStates] = useState<StateRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/states")
      .then((r) => {
        if (!r.ok) throw new Error(`API returned ${r.status}`);
        return r.json();
      })
      .then((d) => setStates(d.states || []))
      .catch(() => setError("Could not load states. The API may be unreachable."))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <Header subtitle="Landlord-tenant laws and renter protections, by state." />

      <main
        className="page-fade-in"
        style={{ maxWidth: 1200, margin: "0 auto", padding: "0 24px 48px", position: "relative", zIndex: 2 }}
      >
        <div className="card" style={{ padding: "20px 24px", marginBottom: 20, boxShadow: "var(--shadow-lg)" }}>
          <Nav />
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Browse by State</h2>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--color-text-muted)", lineHeight: 1.5 }}>
            Pick a state for the top things to know about its landlord-tenant laws and renter protections,
            with links to each official source.
          </p>
        </div>

        {loading && (
          <div className="card" style={{ padding: 48, textAlign: "center", color: "var(--color-text-subtle)" }}>
            Loading states...
          </div>
        )}

        {error && (
          <div className="card" style={{ background: "#fef2f2", borderColor: "#fecaca", padding: "14px 18px", color: "#991b1b", fontSize: 13 }}>
            {error}
          </div>
        )}

        {!loading && !error && states.length === 0 && (
          <div className="card" style={{ textAlign: "center", padding: 56, color: "var(--color-text-subtle)" }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>🗺️</div>
            <div style={{ fontSize: 17, color: "var(--color-text)", fontWeight: 700, marginBottom: 6 }}>
              No state data yet
            </div>
            <div style={{ fontSize: 13, lineHeight: 1.5 }}>
              Once Jeanne has analyzed some bills, states will appear here. Use the Admin panel to pull and analyze data.
            </div>
          </div>
        )}

        {!loading && states.length > 0 && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
              gap: 14,
            }}
          >
            {states.map((s) => (
              <Link
                key={s.state_code}
                href={`/states/${s.state_code}`}
                className="card"
                style={{
                  padding: "18px 20px",
                  textDecoration: "none",
                  color: "inherit",
                  display: "block",
                  transition: "transform 140ms ease, box-shadow 140ms ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = "translateY(-3px)";
                  e.currentTarget.style.boxShadow = "var(--shadow-lg)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = "translateY(0)";
                  e.currentTarget.style.boxShadow = "";
                }}
              >
                <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
                  <span style={{ fontSize: 16, fontWeight: 700 }}>{s.name}</span>
                  <span style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-subtle)" }}>{s.state_code}</span>
                </div>
                <div style={{ fontSize: 12, color: "var(--color-text-muted)", marginTop: 8 }}>
                  <strong style={{ color: "var(--color-primary)" }}>{s.item_count.toLocaleString()}</strong> tracked item
                  {s.item_count !== 1 ? "s" : ""}
                  {s.law_topic_count > 0 && (
                    <>
                      {" · "}
                      <strong>{s.law_topic_count}</strong> law topic{s.law_topic_count !== 1 ? "s" : ""}
                    </>
                  )}
                </div>
              </Link>
            ))}
          </div>
        )}
      </main>

      <AdminControls />
    </div>
  );
}
