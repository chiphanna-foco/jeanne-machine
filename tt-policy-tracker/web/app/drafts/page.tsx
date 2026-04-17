"use client";

import { useEffect, useState } from "react";
import { AdminControls } from "../components/AdminControls";
import { Header } from "../components/Header";
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

const STATUS: Record<string, { bg: string; color: string; label: string }> = {
  draft: { bg: "#e0e7ff", color: "#3730a3", label: "Draft" },
  approved: { bg: "#d1fae5", color: "#065f46", label: "Approved" },
  rejected: { bg: "#fee2e2", color: "#991b1b", label: "Rejected" },
  published: { bg: "#dbeafe", color: "#1e40af", label: "Published" },
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

  const counts = {
    all: drafts.length,
    draft: drafts.filter((d) => d.status === "draft").length,
    approved: drafts.filter((d) => d.status === "approved").length,
    published: drafts.filter((d) => d.status === "published").length,
  };

  return (
    <div>
      <Header subtitle="AI-generated content from high-impact policy items" />

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

          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <StatusPill active={!statusFilter} onClick={() => setStatusFilter("")} label="All" count={counts.all} />
            <StatusPill active={statusFilter === "draft"} onClick={() => setStatusFilter("draft")} label="Draft" color="#3730a3" />
            <StatusPill active={statusFilter === "approved"} onClick={() => setStatusFilter("approved")} label="Approved" color="#065f46" />
            <StatusPill active={statusFilter === "rejected"} onClick={() => setStatusFilter("rejected")} label="Rejected" color="#991b1b" />
            <StatusPill active={statusFilter === "published"} onClick={() => setStatusFilter("published")} label="Published" color="#1e40af" />
          </div>
        </div>

        {loading && (
          <div className="card" style={{ padding: 32, textAlign: "center", color: "var(--color-text-subtle)" }}>
            Loading drafts...
          </div>
        )}

        {error && (
          <div className="card" style={{ background: "#fef2f2", borderColor: "#fecaca", padding: "14px 18px", color: "#991b1b", fontSize: 13, marginBottom: 16 }}>
            {error}
          </div>
        )}

        {!loading && drafts.length === 0 && (
          <div className="card" style={{ textAlign: "center", padding: 48, color: "var(--color-text-subtle)" }}>
            <div style={{ fontSize: 36, marginBottom: 8 }}>✍️</div>
            <div style={{ fontSize: 15, color: "var(--color-text)", fontWeight: 600, marginBottom: 4 }}>
              No drafts yet
            </div>
            <div style={{ fontSize: 13 }}>
              Click <strong>Generate Blog Drafts</strong> in the Admin panel to create drafts from high-impact policy items.
            </div>
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {drafts.map((draft) => {
            const statusStyle = STATUS[draft.status] || STATUS.draft;
            return (
              <button
                key={draft.id}
                onClick={() => setSelected(draft)}
                className="card"
                style={{
                  padding: "18px 22px 18px 26px",
                  position: "relative",
                  textAlign: "left",
                  cursor: "pointer",
                  border: "1px solid var(--color-border)",
                  background: "#fff",
                  transition: "box-shadow 160ms ease",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.boxShadow = "var(--shadow-lg)")}
                onMouseLeave={(e) => (e.currentTarget.style.boxShadow = "var(--shadow-sm)")}
              >
                <div
                  style={{
                    position: "absolute",
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: 4,
                    background: statusStyle.color,
                    borderTopLeftRadius: "var(--radius)",
                    borderBottomLeftRadius: "var(--radius)",
                  }}
                />
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      background: statusStyle.bg,
                      color: statusStyle.color,
                      padding: "3px 10px",
                      borderRadius: 999,
                      letterSpacing: "0.05em",
                    }}
                  >
                    {statusStyle.label}
                  </span>
                  <span style={{ fontSize: 11, color: "var(--color-text-subtle)", fontWeight: 500 }}>
                    {TYPE_LABELS[draft.content_type] || draft.content_type}
                  </span>
                  {draft.generated_at && (
                    <span style={{ fontSize: 11, color: "var(--color-text-subtle)", marginLeft: "auto" }}>
                      {new Date(draft.generated_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                    </span>
                  )}
                </div>
                <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "var(--color-text)", lineHeight: 1.3 }}>
                  {draft.title}
                </h3>
                {draft.seo_description && (
                  <p style={{ margin: "6px 0 0", fontSize: 13, color: "var(--color-text-muted)", lineHeight: 1.5 }}>
                    {draft.seo_description}
                  </p>
                )}
                {draft.suggested_tags && draft.suggested_tags.length > 0 && (
                  <div style={{ display: "flex", gap: 5, marginTop: 10, flexWrap: "wrap" }}>
                    {draft.suggested_tags.slice(0, 5).map((tag) => (
                      <span
                        key={tag}
                        style={{
                          fontSize: 10,
                          background: "#f1f5f9",
                          color: "#475569",
                          padding: "3px 8px",
                          borderRadius: 999,
                          fontWeight: 500,
                        }}
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </main>

      {selected && (
        <DraftDetail
          draft={selected}
          onClose={() => setSelected(null)}
          onStatus={(id, s) => updateStatus(id, s)}
        />
      )}

      <AdminControls />
    </div>
  );
}

function StatusPill({
  active,
  onClick,
  label,
  count,
  color,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count?: number;
  color?: string;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "7px 14px",
        borderRadius: 999,
        border: "1px solid var(--color-border)",
        fontSize: 12,
        fontWeight: 600,
        background: active ? (color || "var(--color-primary)") : "#fff",
        color: active ? "#fff" : "var(--color-text-muted)",
        cursor: "pointer",
        transition: "all 160ms ease",
      }}
    >
      {label}
      {typeof count === "number" && <span style={{ marginLeft: 6, opacity: 0.7 }}>{count}</span>}
    </button>
  );
}

function DraftDetail({
  draft,
  onClose,
  onStatus,
}: {
  draft: ContentDraft;
  onClose: () => void;
  onStatus: (id: number, status: string) => void;
}) {
  const statusStyle = STATUS[draft.status] || STATUS.draft;

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
        padding: "32px 16px",
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
          maxWidth: 780,
          width: "100%",
          maxHeight: "90vh",
          overflowY: "auto",
          boxShadow: "0 25px 50px -12px rgba(0,0,0,0.25)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, marginBottom: 16 }}>
          <div style={{ flex: 1 }}>
            <div
              style={{
                display: "flex",
                gap: 8,
                alignItems: "center",
                marginBottom: 8,
              }}
            >
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  background: statusStyle.bg,
                  color: statusStyle.color,
                  padding: "3px 10px",
                  borderRadius: 999,
                  letterSpacing: "0.05em",
                }}
              >
                {statusStyle.label}
              </span>
              <span style={{ fontSize: 11, color: "var(--color-text-subtle)", fontWeight: 500 }}>
                {TYPE_LABELS[draft.content_type] || draft.content_type}
              </span>
            </div>
            <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em", lineHeight: 1.3 }}>
              {draft.title}
            </h2>
            {draft.seo_description && (
              <p style={{ margin: "8px 0 0", fontSize: 13, color: "var(--color-text-muted)", fontStyle: "italic", lineHeight: 1.5 }}>
                {draft.seo_description}
              </p>
            )}
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

        <div style={{ display: "flex", gap: 8, marginBottom: 20, flexWrap: "wrap" }}>
          {draft.status !== "approved" && (
            <ActionButton color="#059669" onClick={() => onStatus(draft.id, "approved")}>
              Approve
            </ActionButton>
          )}
          {draft.status !== "rejected" && (
            <ActionButton color="#dc2626" onClick={() => onStatus(draft.id, "rejected")}>
              Reject
            </ActionButton>
          )}
          {draft.status === "approved" && (
            <ActionButton color="#1e40af" onClick={() => onStatus(draft.id, "published")}>
              Mark Published
            </ActionButton>
          )}
          <ActionButton outline onClick={() => navigator.clipboard?.writeText(draft.body)}>
            Copy Body
          </ActionButton>
        </div>

        <div
          style={{
            background: "#fafbfc",
            border: "1px solid var(--color-border)",
            borderRadius: 10,
            padding: 22,
            fontSize: 14,
            lineHeight: 1.75,
            color: "var(--color-text)",
            whiteSpace: "pre-wrap",
          }}
        >
          {draft.body}
        </div>

        {draft.suggested_tags && draft.suggested_tags.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <span style={{ fontSize: 11, color: "var(--color-text-subtle)", fontWeight: 600, marginRight: 8, textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Suggested Tags
            </span>
            {draft.suggested_tags.map((tag) => (
              <span
                key={tag}
                style={{
                  display: "inline-block",
                  fontSize: 11,
                  background: "#e0e7ff",
                  color: "#3730a3",
                  padding: "3px 10px",
                  borderRadius: 999,
                  marginRight: 5,
                  marginTop: 4,
                  fontWeight: 500,
                }}
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ActionButton({
  children,
  color,
  outline,
  onClick,
}: {
  children: React.ReactNode;
  color?: string;
  outline?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "8px 16px",
        fontSize: 12,
        fontWeight: 600,
        background: outline ? "transparent" : color,
        color: outline ? "var(--color-text-muted)" : "#fff",
        border: outline ? "1px solid var(--color-border-strong)" : "none",
        borderRadius: 8,
        cursor: "pointer",
        transition: "opacity 160ms ease",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.88")}
      onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
    >
      {children}
    </button>
  );
}
