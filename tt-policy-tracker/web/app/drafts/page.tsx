"use client";

import { useEffect, useState } from "react";
import { AdminControls } from "../components/AdminControls";
import { Nav } from "../components/Nav";

interface ContentDraft {
  id: number;
  policy_item_id: number;
  content_type: string;
  title: string;
  body: string;
  seo_description: string | null;
  suggested_tags: string[] | null;
  status: string;
  generated_at: string | null;
}

const STATUS_COLORS: Record<string, { bg: string; text: string }> = {
  draft: { bg: "#e0e7ff", text: "#3730a3" },
  approved: { bg: "#d1fae5", text: "#065f46" },
  rejected: { bg: "#fee2e2", text: "#991b1b" },
  published: { bg: "#dbeafe", text: "#1e40af" },
};

const TYPE_LABELS: Record<string, string> = {
  blog_post: "Blog Post",
  social_post: "Social Post",
  newsletter_blurb: "Newsletter",
};

export default function DraftsPage() {
  const [drafts, setDrafts] = useState<ContentDraft[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ContentDraft | null>(null);
  const [statusFilter, setStatusFilter] = useState("");

  const fetchDrafts = () => {
    setLoading(true);
    const params = new URLSearchParams();
    if (statusFilter) params.set("status", statusFilter);

    fetch(`/api/drafts?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`API returned ${r.status}`);
        return r.json();
      })
      .then((data) => setDrafts(data.drafts || []))
      .catch((err) => {
        console.error("Failed to fetch drafts:", err);
        setError("Could not load drafts.");
      })
      .finally(() => setLoading(false));
  };

  useEffect(fetchDrafts, [statusFilter]);

  const updateStatus = async (draftId: number, newStatus: string) => {
    try {
      const resp = await fetch(`/api/drafts/${draftId}/status?new_status=${newStatus}`, {
        method: "POST",
      });
      if (resp.ok) {
        fetchDrafts();
        if (selected?.id === draftId) {
          setSelected({ ...selected, status: newStatus });
        }
      }
    } catch (err) {
      console.error("Failed to update status:", err);
    }
  };

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "24px 16px" }}>
      <header style={{ marginBottom: 16 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: "#1a56db", margin: 0 }}>
          TT Policy Tracker
        </h1>
        <p style={{ color: "#6b7280", fontSize: 14, margin: "4px 0 0 0" }}>
          AI-generated content drafts from high-impact policy items
        </p>
      </header>

      <Nav />

      <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{
            padding: "8px 12px",
            borderRadius: 6,
            border: "1px solid #d1d5db",
            fontSize: 13,
            background: "#fff",
          }}
        >
          <option value="">All Statuses</option>
          <option value="draft">Draft</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="published">Published</option>
        </select>
      </div>

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
            marginBottom: 16,
          }}
        >
          {error}
        </div>
      )}

      {!loading && drafts.length === 0 && (
        <div style={{ textAlign: "center", padding: 48, color: "#9ca3af" }}>
          No content drafts yet. Use the Admin panel to generate drafts from high-impact policy items.
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {drafts.map((draft) => {
          const statusStyle = STATUS_COLORS[draft.status] || STATUS_COLORS.draft;
          return (
            <div
              key={draft.id}
              onClick={() => setSelected(draft)}
              style={{
                background: "#fff",
                borderRadius: 8,
                padding: "16px 20px",
                boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
                cursor: "pointer",
                borderLeft: `4px solid ${statusStyle.text}`,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    background: statusStyle.bg,
                    color: statusStyle.text,
                    padding: "2px 8px",
                    borderRadius: 4,
                  }}
                >
                  {draft.status}
                </span>
                <span style={{ fontSize: 11, color: "#6b7280" }}>
                  {TYPE_LABELS[draft.content_type] || draft.content_type}
                </span>
                {draft.generated_at && (
                  <span style={{ fontSize: 11, color: "#9ca3af", marginLeft: "auto" }}>
                    {new Date(draft.generated_at).toLocaleDateString()}
                  </span>
                )}
              </div>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: "#1f2937" }}>
                {draft.title}
              </h3>
              {draft.seo_description && (
                <p style={{ margin: "4px 0 0", fontSize: 13, color: "#6b7280" }}>
                  {draft.seo_description}
                </p>
              )}
              {draft.suggested_tags && draft.suggested_tags.length > 0 && (
                <div style={{ display: "flex", gap: 4, marginTop: 8, flexWrap: "wrap" }}>
                  {draft.suggested_tags.map((tag) => (
                    <span
                      key={tag}
                      style={{
                        fontSize: 10,
                        background: "#f3f4f6",
                        color: "#4b5563",
                        padding: "2px 6px",
                        borderRadius: 10,
                      }}
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Detail modal */}
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
            padding: "32px 16px",
            zIndex: 50,
            overflowY: "auto",
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "#fff",
              borderRadius: 12,
              padding: 24,
              maxWidth: 760,
              width: "100%",
              maxHeight: "90vh",
              overflowY: "auto",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: 11, color: "#6b7280", textTransform: "uppercase" }}>
                  {TYPE_LABELS[selected.content_type] || selected.content_type}
                </div>
                <h2 style={{ margin: "4px 0", fontSize: 20, fontWeight: 700 }}>{selected.title}</h2>
                {selected.seo_description && (
                  <p style={{ fontSize: 13, color: "#6b7280", margin: "4px 0", fontStyle: "italic" }}>
                    {selected.seo_description}
                  </p>
                )}
              </div>
              <button
                onClick={() => setSelected(null)}
                style={{ background: "transparent", border: "none", fontSize: 20, cursor: "pointer", color: "#6b7280" }}
              >
                ×
              </button>
            </div>

            {/* Status actions */}
            <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
              {selected.status !== "approved" && (
                <button
                  onClick={() => updateStatus(selected.id, "approved")}
                  style={{
                    padding: "6px 14px",
                    fontSize: 12,
                    fontWeight: 600,
                    background: "#059669",
                    color: "#fff",
                    border: "none",
                    borderRadius: 6,
                    cursor: "pointer",
                  }}
                >
                  Approve
                </button>
              )}
              {selected.status !== "rejected" && (
                <button
                  onClick={() => updateStatus(selected.id, "rejected")}
                  style={{
                    padding: "6px 14px",
                    fontSize: 12,
                    fontWeight: 600,
                    background: "#dc2626",
                    color: "#fff",
                    border: "none",
                    borderRadius: 6,
                    cursor: "pointer",
                  }}
                >
                  Reject
                </button>
              )}
              {selected.status === "approved" && (
                <button
                  onClick={() => updateStatus(selected.id, "published")}
                  style={{
                    padding: "6px 14px",
                    fontSize: 12,
                    fontWeight: 600,
                    background: "#1a56db",
                    color: "#fff",
                    border: "none",
                    borderRadius: 6,
                    cursor: "pointer",
                  }}
                >
                  Mark Published
                </button>
              )}
            </div>

            {/* Body content */}
            <div
              style={{
                background: "#f9fafb",
                borderRadius: 8,
                padding: 20,
                fontSize: 14,
                lineHeight: 1.7,
                color: "#1f2937",
                whiteSpace: "pre-wrap",
              }}
            >
              {selected.body}
            </div>

            {selected.suggested_tags && selected.suggested_tags.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <span style={{ fontSize: 12, color: "#6b7280" }}>Suggested tags: </span>
                {selected.suggested_tags.map((tag) => (
                  <span
                    key={tag}
                    style={{
                      fontSize: 11,
                      background: "#e0e7ff",
                      color: "#3730a3",
                      padding: "2px 8px",
                      borderRadius: 12,
                      marginRight: 4,
                    }}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <AdminControls />
    </div>
  );
}
