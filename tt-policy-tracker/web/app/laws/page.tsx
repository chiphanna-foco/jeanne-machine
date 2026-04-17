"use client";

import { useEffect, useMemo, useState } from "react";
import { AdminControls } from "../components/AdminControls";
import { Header } from "../components/Header";
import { Nav } from "../components/Nav";

interface LawSnapshot {
  id: number;
  jurisdiction_id: number;
  topic: string;
  headline: string | null;
  summary: string;
  key_facts: string[] | null;
  statutory_references: string[] | null;
  source_item_ids: number[] | null;
  confidence: "low" | "med" | "high";
  caveats: string | null;
  updated_at: string | null;
}

interface MatrixJurisdiction {
  jurisdiction_id: number;
  jurisdiction_name: string;
  jurisdiction_level: string;
  state_code: string | null;
  topics: Record<string, { confidence: string; headline: string | null; snapshot_id: number } | null>;
}

interface MatrixResponse {
  topics: string[];
  topic_labels: Record<string, string>;
  jurisdictions: MatrixJurisdiction[];
}

const CONFIDENCE: Record<string, { color: string; bg: string; label: string }> = {
  high: { color: "#059669", bg: "#d1fae5", label: "HIGH" },
  med: { color: "#d97706", bg: "#fef3c7", label: "MED" },
  low: { color: "#dc2626", bg: "#fee2e2", label: "LOW" },
};

export default function LawsPage() {
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null);
  const [selected, setSelected] = useState<LawSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/laws/matrix")
      .then((r) => {
        if (!r.ok) throw new Error(`API returned ${r.status}`);
        return r.json();
      })
      .then((data: MatrixResponse) => setMatrix(data))
      .catch((err) => {
        console.error("Failed to fetch law matrix:", err);
        setError("Could not load law snapshots. The API may be unreachable.");
      })
      .finally(() => setLoading(false));
  }, []);

  const openSnapshot = async (snapshotId: number) => {
    try {
      const resp = await fetch("/api/laws");
      const data = await resp.json();
      const snap = data.snapshots.find((s: LawSnapshot) => s.id === snapshotId);
      if (snap) setSelected(snap);
    } catch (err) {
      console.error("Failed to load snapshot:", err);
    }
  };

  const topicsWithCoverage = useMemo(() => {
    if (!matrix) return [];
    return matrix.topics.filter((t) =>
      matrix.jurisdictions.some((j) => j.topics[t] !== null)
    );
  }, [matrix]);

  return (
    <div>
      <Header subtitle="Every housing law, every jurisdiction, AI-synthesized." />

      <main
        className="page-fade-in"
        style={{
          maxWidth: 1200,
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

          <div style={{ marginBottom: 4 }}>
            <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Current Laws Matrix</h2>
            <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--color-text-muted)", lineHeight: 1.5 }}>
              AI-synthesized summaries of current law by jurisdiction and topic.
              Color indicates data confidence.
              <ConfidenceDot color={CONFIDENCE.high.color} label="high" />
              <ConfidenceDot color={CONFIDENCE.med.color} label="med" />
              <ConfidenceDot color={CONFIDENCE.low.color} label="low" />
              {" "}Click any cell for details.
            </p>
          </div>
        </div>

        {loading && (
          <div className="card" style={{ padding: 48, textAlign: "center", color: "var(--color-text-subtle)" }}>
            Loading law repository...
          </div>
        )}

        {error && (
          <div
            className="card"
            style={{
              background: "#fef2f2",
              borderColor: "#fecaca",
              padding: "14px 18px",
              color: "#991b1b",
              fontSize: 13,
            }}
          >
            {error}
          </div>
        )}

        {!loading && matrix && matrix.jurisdictions.length === 0 && (
          <div className="card" style={{ textAlign: "center", padding: 56, color: "var(--color-text-subtle)" }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>📚</div>
            <div style={{ fontSize: 17, color: "var(--color-text)", fontWeight: 700, marginBottom: 6, letterSpacing: "-0.01em" }}>
              Library&apos;s looking empty
            </div>
            <div style={{ fontSize: 13, lineHeight: 1.5 }}>
              Once Jeanne has some policy items to work with, hit <strong>Refresh Current Laws</strong> in the Admin panel.
            </div>
          </div>
        )}

        {!loading && matrix && matrix.jurisdictions.length > 0 && (
          <div className="card" style={{ overflowX: "auto", padding: 0 }}>
            <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
              <thead>
                <tr style={{ background: "#f9fafb", borderBottom: "1px solid var(--color-border)" }}>
                  <th
                    style={{
                      padding: "14px 16px",
                      textAlign: "left",
                      fontWeight: 600,
                      fontSize: 11,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      color: "var(--color-text-muted)",
                      position: "sticky",
                      left: 0,
                      background: "#f9fafb",
                      minWidth: 200,
                      zIndex: 2,
                    }}
                  >
                    Jurisdiction
                  </th>
                  {topicsWithCoverage.map((topic) => (
                    <th
                      key={topic}
                      style={{
                        padding: "14px 12px",
                        textAlign: "left",
                        fontWeight: 600,
                        fontSize: 11,
                        textTransform: "uppercase",
                        letterSpacing: "0.03em",
                        color: "var(--color-text-muted)",
                        minWidth: 170,
                      }}
                    >
                      {matrix.topic_labels[topic] || topic}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.jurisdictions.map((jur, rowIdx) => (
                  <tr key={jur.jurisdiction_id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                    <td
                      style={{
                        padding: "12px 16px",
                        fontWeight: 600,
                        position: "sticky",
                        left: 0,
                        background: rowIdx % 2 === 0 ? "#fff" : "#fafbfc",
                        zIndex: 1,
                      }}
                    >
                      <div>{jur.jurisdiction_name}</div>
                      <div
                        style={{
                          fontSize: 10,
                          color: "var(--color-text-subtle)",
                          textTransform: "uppercase",
                          fontWeight: 500,
                          marginTop: 2,
                          letterSpacing: "0.05em",
                        }}
                      >
                        {jur.jurisdiction_level}
                        {jur.state_code && ` · ${jur.state_code}`}
                      </div>
                    </td>
                    {topicsWithCoverage.map((topic) => {
                      const cell = jur.topics[topic];
                      if (!cell) {
                        return (
                          <td key={topic} style={{ padding: "10px 12px", color: "#d1d5db", fontSize: 16 }}>
                            —
                          </td>
                        );
                      }
                      const conf = CONFIDENCE[cell.confidence] || CONFIDENCE.med;
                      return (
                        <td key={topic} style={{ padding: "6px 10px" }}>
                          <button
                            onClick={() => openSnapshot(cell.snapshot_id)}
                            style={{
                              background: conf.bg,
                              border: "none",
                              borderLeft: `3px solid ${conf.color}`,
                              padding: "8px 12px",
                              borderRadius: 6,
                              fontSize: 11,
                              color: "#374151",
                              cursor: "pointer",
                              textAlign: "left",
                              width: "100%",
                              lineHeight: 1.4,
                              fontWeight: 500,
                              transition: "transform 100ms ease",
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.transform = "scale(1.02)")}
                            onMouseLeave={(e) => (e.currentTarget.style.transform = "scale(1)")}
                          >
                            {cell.headline || conf.label}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </main>

      {selected && (
        <SnapshotDetail snapshot={selected} onClose={() => setSelected(null)} />
      )}

      <AdminControls />
    </div>
  );
}

function ConfidenceDot({ color, label }: { color: string; label: string }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 3,
        margin: "0 4px 0 8px",
      }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: color,
          display: "inline-block",
        }}
      />
      <span style={{ fontSize: 12 }}>{label}</span>
    </span>
  );
}

function SnapshotDetail({ snapshot, onClose }: { snapshot: LawSnapshot; onClose: () => void }) {
  const conf = CONFIDENCE[snapshot.confidence] || CONFIDENCE.med;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15, 23, 42, 0.4)",
        backdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: "48px 16px",
        zIndex: 60,
        overflowY: "auto",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: 14,
          padding: 28,
          maxWidth: 720,
          width: "100%",
          maxHeight: "85vh",
          overflowY: "auto",
          boxShadow: "0 25px 50px -12px rgba(0,0,0,0.25)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 16 }}>
          <div>
            <div
              style={{
                fontSize: 10,
                color: "var(--color-text-subtle)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                fontWeight: 600,
              }}
            >
              {snapshot.topic.replace(/_/g, " ")}
            </div>
            <h2 style={{ margin: "6px 0 0", fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em", lineHeight: 1.3 }}>
              {snapshot.headline || "Current Law Summary"}
            </h2>
          </div>
          <button
            onClick={onClose}
            style={{
              background: "#f1f5f9",
              border: "none",
              width: 32,
              height: 32,
              borderRadius: 8,
              fontSize: 16,
              cursor: "pointer",
              color: "var(--color-text-muted)",
              flexShrink: 0,
            }}
          >
            ×
          </button>
        </div>

        <span
          style={{
            display: "inline-block",
            fontSize: 10,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            color: conf.color,
            background: conf.bg,
            padding: "4px 10px",
            borderRadius: 999,
            marginBottom: 18,
          }}
        >
          {snapshot.confidence} confidence
        </span>

        <p style={{ fontSize: 15, lineHeight: 1.7, color: "var(--color-text)", margin: "0 0 16px" }}>
          {snapshot.summary}
        </p>

        {snapshot.key_facts && snapshot.key_facts.length > 0 && (
          <section style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--color-text-muted)", margin: "0 0 8px" }}>
              Key Facts
            </h3>
            <ul style={{ paddingLeft: 22, fontSize: 14, lineHeight: 1.6, margin: 0 }}>
              {snapshot.key_facts.map((fact, i) => (
                <li key={i} style={{ marginBottom: 4 }}>{fact}</li>
              ))}
            </ul>
          </section>
        )}

        {snapshot.statutory_references && snapshot.statutory_references.length > 0 && (
          <section style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--color-text-muted)", margin: "0 0 8px" }}>
              Statutory References
            </h3>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {snapshot.statutory_references.map((ref, i) => (
                <code
                  key={i}
                  style={{
                    background: "#f1f5f9",
                    padding: "4px 10px",
                    borderRadius: 6,
                    fontSize: 12,
                    fontWeight: 500,
                  }}
                >
                  {ref}
                </code>
              ))}
            </div>
          </section>
        )}

        {snapshot.caveats && (
          <div
            style={{
              background: "#fef3c7",
              border: "1px solid #fde68a",
              borderRadius: 8,
              padding: "10px 14px",
              fontSize: 12,
              color: "#713f12",
              lineHeight: 1.5,
            }}
          >
            <strong>Note:</strong> {snapshot.caveats}
          </div>
        )}

        {snapshot.source_item_ids && snapshot.source_item_ids.length > 0 && (
          <div style={{ marginTop: 14, fontSize: 11, color: "var(--color-text-subtle)" }}>
            Synthesized from {snapshot.source_item_ids.length} policy item{snapshot.source_item_ids.length !== 1 ? "s" : ""}
            {snapshot.updated_at && ` · Updated ${new Date(snapshot.updated_at).toLocaleDateString()}`}.
          </div>
        )}
      </div>
    </div>
  );
}
