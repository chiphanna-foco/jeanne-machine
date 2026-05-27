"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { AdminControls } from "../../components/AdminControls";
import { Header } from "../../components/Header";
import { Nav } from "../../components/Nav";

interface LawSnapshot {
  id: number;
  topic: string;
  headline: string | null;
  summary: string;
  key_facts: string[] | null;
  statutory_references: string[] | null;
  confidence: "low" | "med" | "high";
  caveats: string | null;
}

interface Item {
  id: number;
  title: string;
  summary: string;
  impact_score: "low" | "med" | "high";
  action_needed: string | null;
  topics: string[] | null;
  source_url: string | null;
  effective_date: string | null;
}

interface Guide {
  state_code: string;
  name: string;
  topic_labels: Record<string, string>;
  law_snapshots: LawSnapshot[];
  top_items: Item[];
}

const IMPACT: Record<string, { bg: string; color: string; label: string }> = {
  high: { bg: "#fee2e2", color: "#dc2626", label: "HIGH IMPACT" },
  med: { bg: "#fef3c7", color: "#d97706", label: "MEDIUM" },
  low: { bg: "#f1f5f9", color: "#64748b", label: "LOW" },
};

export default function StateGuidePage() {
  const params = useParams();
  const code = String(params.state || "").toUpperCase();
  const [guide, setGuide] = useState<Guide | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    fetch(`/api/states/${code}`)
      .then((r) => {
        if (!r.ok) throw new Error(`API returned ${r.status}`);
        return r.json();
      })
      .then((d: Guide) => setGuide(d))
      .catch(() => setError("Could not load this state's guide. The API may be unreachable."))
      .finally(() => setLoading(false));
  }, [code]);

  const label = (topic: string) =>
    guide?.topic_labels?.[topic] || topic.replace(/_/g, " ");

  return (
    <div>
      <Header subtitle={guide ? `${guide.name}: landlord-tenant laws & renter protections` : "State guide"} />

      <main
        className="page-fade-in"
        style={{ maxWidth: 1000, margin: "0 auto", padding: "0 24px 48px", position: "relative", zIndex: 2 }}
      >
        <div className="card" style={{ padding: "20px 24px", marginBottom: 20, boxShadow: "var(--shadow-lg)" }}>
          <Nav />
          <Link href="/states" style={{ fontSize: 12, color: "var(--color-text-muted)", textDecoration: "none" }}>
            ← All states
          </Link>
          <h2 style={{ margin: "8px 0 0", fontSize: 22, fontWeight: 700 }}>
            {guide ? guide.name : code}
          </h2>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--color-text-muted)", lineHeight: 1.5 }}>
            Top things to know, AI-summarized from tracked legislation. Each item links to its official source.
          </p>
        </div>

        {loading && (
          <div className="card" style={{ padding: 48, textAlign: "center", color: "var(--color-text-subtle)" }}>
            Loading {code} guide...
          </div>
        )}

        {error && (
          <div className="card" style={{ background: "#fef2f2", borderColor: "#fecaca", padding: "14px 18px", color: "#991b1b", fontSize: 13 }}>
            {error}
          </div>
        )}

        {!loading && guide && guide.law_snapshots.length === 0 && guide.top_items.length === 0 && (
          <div className="card" style={{ textAlign: "center", padding: 56, color: "var(--color-text-subtle)" }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>📭</div>
            <div style={{ fontSize: 17, color: "var(--color-text)", fontWeight: 700, marginBottom: 6 }}>
              Nothing tracked for {guide.name} yet
            </div>
            <div style={{ fontSize: 13, lineHeight: 1.5 }}>
              Pull and analyze data for this state from the Admin panel, then check back.
            </div>
          </div>
        )}

        {/* AI law summaries */}
        {!loading && guide && guide.law_snapshots.length > 0 && (
          <section style={{ marginBottom: 24 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, margin: "0 0 12px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              What the law says
            </h3>
            <div style={{ display: "grid", gap: 14 }}>
              {guide.law_snapshots.map((s) => (
                <div key={s.id} className="card" style={{ padding: "18px 22px" }}>
                  <div style={{ fontSize: 10, color: "var(--color-text-subtle)", textTransform: "uppercase", letterSpacing: "0.08em", fontWeight: 600 }}>
                    {label(s.topic)}
                  </div>
                  <h4 style={{ margin: "4px 0 8px", fontSize: 17, fontWeight: 700, lineHeight: 1.3 }}>
                    {s.headline || "Current law summary"}
                  </h4>
                  <p style={{ fontSize: 14, lineHeight: 1.65, color: "var(--color-text)", margin: "0 0 10px" }}>
                    {s.summary}
                  </p>
                  {s.key_facts && s.key_facts.length > 0 && (
                    <ul style={{ paddingLeft: 20, fontSize: 13, lineHeight: 1.6, margin: "0 0 8px" }}>
                      {s.key_facts.map((f, i) => (
                        <li key={i} style={{ marginBottom: 3 }}>{f}</li>
                      ))}
                    </ul>
                  )}
                  {s.statutory_references && s.statutory_references.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                      {s.statutory_references.map((ref, i) => (
                        <code key={i} style={{ background: "#f1f5f9", padding: "3px 8px", borderRadius: 6, fontSize: 11, fontWeight: 500 }}>
                          {ref}
                        </code>
                      ))}
                    </div>
                  )}
                  {s.caveats && (
                    <div style={{ marginTop: 10, fontSize: 11, color: "#92400e", background: "#fef3c7", border: "1px solid #fde68a", borderRadius: 8, padding: "8px 12px", lineHeight: 1.5 }}>
                      <strong>Note:</strong> {s.caveats}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Top tracked items */}
        {!loading && guide && guide.top_items.length > 0 && (
          <section>
            <h3 style={{ fontSize: 14, fontWeight: 700, margin: "0 0 12px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Top bills & rulings to know
            </h3>
            <div style={{ display: "grid", gap: 12 }}>
              {guide.top_items.map((it) => {
                const impact = IMPACT[it.impact_score] || IMPACT.low;
                return (
                  <div key={it.id} className="card" style={{ padding: "16px 20px" }}>
                    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
                      <h4 style={{ margin: 0, fontSize: 15, fontWeight: 700, lineHeight: 1.4 }}>{it.title}</h4>
                      <span
                        style={{
                          flexShrink: 0,
                          fontSize: 9,
                          fontWeight: 700,
                          textTransform: "uppercase",
                          letterSpacing: "0.05em",
                          color: impact.color,
                          background: impact.bg,
                          padding: "3px 8px",
                          borderRadius: 999,
                        }}
                      >
                        {impact.label}
                      </span>
                    </div>
                    <p style={{ fontSize: 13, lineHeight: 1.6, color: "var(--color-text-muted)", margin: "8px 0 0" }}>
                      {it.summary}
                    </p>
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center", marginTop: 10 }}>
                      {(it.topics || []).map((t) => (
                        <span key={t} style={{ fontSize: 10, color: "var(--color-text-subtle)", background: "#f1f5f9", padding: "2px 8px", borderRadius: 999 }}>
                          {label(t)}
                        </span>
                      ))}
                      {it.source_url && (
                        <a
                          href={it.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ marginLeft: "auto", fontSize: 12, fontWeight: 700, color: "var(--color-primary)", textDecoration: "none" }}
                        >
                          View official source ↗
                        </a>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </main>

      <AdminControls />
    </div>
  );
}
