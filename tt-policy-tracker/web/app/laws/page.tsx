"use client";

import { useEffect, useMemo, useState } from "react";
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

const CONFIDENCE_COLOR: Record<string, string> = {
  high: "#059669",
  med: "#f59e0b",
  low: "#dc2626",
};

const CONFIDENCE_BG: Record<string, string> = {
  high: "#d1fae5",
  med: "#fef3c7",
  low: "#fee2e2",
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
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: "24px 16px" }}>
      <header style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: "#1a56db", margin: 0 }}>
          TT Policy Tracker
        </h1>
        <p style={{ color: "#6b7280", fontSize: 14, margin: "4px 0 0 0" }}>
          Current state of law by jurisdiction and topic
        </p>
      </header>

      <Nav />

      {loading && <div style={{ padding: 24, color: "#6b7280" }}>Loading...</div>}

      {error && (
        <div
          style={{
            background: "#fef2f2",
            border: "1px solid #fecaca",
            borderRadius: 8,
            padding: "12px 16px",
            color: "#991b1b",
            fontSize: 13,
          }}
        >
          {error}
        </div>
      )}

      {!loading && matrix && matrix.jurisdictions.length === 0 && (
        <div
          style={{
            textAlign: "center",
            padding: 48,
            color: "#9ca3af",
          }}
        >
          No law snapshots yet. Run <code>/admin/refresh-laws</code> after the pipeline has enriched some items.
        </div>
      )}

      {!loading && matrix && matrix.jurisdictions.length > 0 && (
        <div>
          <p style={{ fontSize: 13, color: "#6b7280", marginBottom: 12 }}>
            AI-synthesized summaries of current law based on observed policy activity.
            Confidence color indicates how certain we are: <span style={{ color: "#059669" }}>green</span> = high,
            {" "}<span style={{ color: "#f59e0b" }}>yellow</span> = medium,
            {" "}<span style={{ color: "#dc2626" }}>red</span> = low.
            Click a cell to see details.
          </p>

          <div style={{ overflowX: "auto", background: "#fff", borderRadius: 8, boxShadow: "0 1px 3px rgba(0,0,0,0.06)" }}>
            <table style={{ borderCollapse: "collapse", fontSize: 13, width: "100%" }}>
              <thead>
                <tr>
                  <th
                    style={{
                      padding: "10px 12px",
                      borderBottom: "2px solid #e5e7eb",
                      textAlign: "left",
                      background: "#f9fafb",
                      position: "sticky",
                      left: 0,
                      minWidth: 180,
                    }}
                  >
                    Jurisdiction
                  </th>
                  {topicsWithCoverage.map((topic) => (
                    <th
                      key={topic}
                      style={{
                        padding: "10px 8px",
                        borderBottom: "2px solid #e5e7eb",
                        textAlign: "left",
                        background: "#f9fafb",
                        fontWeight: 600,
                        fontSize: 11,
                        minWidth: 140,
                      }}
                    >
                      {matrix.topic_labels[topic] || topic}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrix.jurisdictions.map((jur) => (
                  <tr key={jur.jurisdiction_id}>
                    <td
                      style={{
                        padding: "10px 12px",
                        borderBottom: "1px solid #f3f4f6",
                        fontWeight: 500,
                        position: "sticky",
                        left: 0,
                        background: "#fff",
                      }}
                    >
                      {jur.jurisdiction_name}
                      <div style={{ fontSize: 10, color: "#9ca3af", textTransform: "uppercase" }}>
                        {jur.jurisdiction_level}
                      </div>
                    </td>
                    {topicsWithCoverage.map((topic) => {
                      const cell = jur.topics[topic];
                      if (!cell) {
                        return (
                          <td
                            key={topic}
                            style={{
                              padding: "8px",
                              borderBottom: "1px solid #f3f4f6",
                              color: "#d1d5db",
                              fontSize: 11,
                            }}
                          >
                            —
                          </td>
                        );
                      }
                      return (
                        <td
                          key={topic}
                          onClick={() => openSnapshot(cell.snapshot_id)}
                          style={{
                            padding: "6px 8px",
                            borderBottom: "1px solid #f3f4f6",
                            background: CONFIDENCE_BG[cell.confidence] || "#f9fafb",
                            borderLeft: `3px solid ${CONFIDENCE_COLOR[cell.confidence] || "#6b7280"}`,
                            cursor: "pointer",
                            fontSize: 11,
                            color: "#374151",
                          }}
                        >
                          {cell.headline || cell.confidence.toUpperCase()}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {selected && (
        <div
          onClick={() => setSelected(null)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "center",
            padding: "48px 16px",
            zIndex: 50,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "#fff",
              borderRadius: 12,
              padding: 24,
              maxWidth: 720,
              width: "100%",
              maxHeight: "85vh",
              overflowY: "auto",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 12 }}>
              <div>
                <div style={{ fontSize: 11, color: "#6b7280", textTransform: "uppercase", letterSpacing: 0.05 }}>
                  {selected.topic.replace(/_/g, " ")}
                </div>
                <h2 style={{ margin: "4px 0", fontSize: 18, fontWeight: 700 }}>
                  {selected.headline || "Current Law Summary"}
                </h2>
              </div>
              <button
                onClick={() => setSelected(null)}
                style={{
                  background: "transparent",
                  border: "none",
                  fontSize: 20,
                  cursor: "pointer",
                  color: "#6b7280",
                  padding: 4,
                }}
              >
                ×
              </button>
            </div>

            <span
              style={{
                display: "inline-block",
                fontSize: 10,
                fontWeight: 600,
                textTransform: "uppercase",
                color: CONFIDENCE_COLOR[selected.confidence],
                background: CONFIDENCE_BG[selected.confidence],
                padding: "2px 8px",
                borderRadius: 4,
                marginBottom: 12,
              }}
            >
              {selected.confidence} confidence
            </span>

            <p style={{ fontSize: 14, lineHeight: 1.6, color: "#1f2937" }}>{selected.summary}</p>

            {selected.key_facts && selected.key_facts.length > 0 && (
              <>
                <h3 style={{ fontSize: 13, fontWeight: 600, marginTop: 16, marginBottom: 6, color: "#374151" }}>Key facts</h3>
                <ul style={{ paddingLeft: 20, fontSize: 13, lineHeight: 1.5 }}>
                  {selected.key_facts.map((fact, i) => (
                    <li key={i}>{fact}</li>
                  ))}
                </ul>
              </>
            )}

            {selected.statutory_references && selected.statutory_references.length > 0 && (
              <>
                <h3 style={{ fontSize: 13, fontWeight: 600, marginTop: 16, marginBottom: 6, color: "#374151" }}>Statutory references</h3>
                <ul style={{ paddingLeft: 20, fontSize: 13, lineHeight: 1.5 }}>
                  {selected.statutory_references.map((ref, i) => (
                    <li key={i}>
                      <code style={{ background: "#f3f4f6", padding: "1px 4px", borderRadius: 3 }}>{ref}</code>
                    </li>
                  ))}
                </ul>
              </>
            )}

            {selected.caveats && (
              <div
                style={{
                  marginTop: 16,
                  background: "#fefce8",
                  border: "1px solid #fef08a",
                  borderRadius: 6,
                  padding: "8px 12px",
                  fontSize: 12,
                  color: "#854d0e",
                }}
              >
                <strong>Note:</strong> {selected.caveats}
              </div>
            )}

            {selected.source_item_ids && selected.source_item_ids.length > 0 && (
              <div style={{ marginTop: 12, fontSize: 11, color: "#9ca3af" }}>
                Synthesized from {selected.source_item_ids.length} policy item{selected.source_item_ids.length !== 1 ? "s" : ""}.
                {selected.updated_at && ` Last updated ${new Date(selected.updated_at).toLocaleDateString()}.`}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
