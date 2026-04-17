"use client";

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
}

const IMPACT: Record<string, { color: string; bg: string; label: string }> = {
  high: { color: "#dc2626", bg: "#fef2f2", label: "HIGH" },
  med: { color: "#d97706", bg: "#fffbeb", label: "MED" },
  low: { color: "#059669", bg: "#ecfdf5", label: "LOW" },
};

const ACTION: Record<string, { label: string; color: string; bg: string }> = {
  urgent: { label: "Urgent", color: "#dc2626", bg: "#fef2f2" },
  monitor: { label: "Monitor", color: "#d97706", bg: "#fffbeb" },
  inform: { label: "Inform", color: "#64748b", bg: "#f1f5f9" },
};

function formatTopic(tag: string): string {
  return tag
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function PolicyItemCard({ item }: { item: PolicyItem }) {
  const impact = IMPACT[item.impact_score] || IMPACT.low;
  const action = item.action_needed ? ACTION[item.action_needed] : null;

  return (
    <article
      className="card"
      style={{
        position: "relative",
        padding: "18px 22px 18px 26px",
        transition: "transform 160ms ease, box-shadow 160ms ease",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.boxShadow = "var(--shadow-lg)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.boxShadow = "var(--shadow-sm)";
      }}
    >
      {/* Left accent bar */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          bottom: 0,
          width: 4,
          background: impact.color,
          borderTopLeftRadius: "var(--radius)",
          borderBottomLeftRadius: "var(--radius)",
        }}
      />

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {/* Header: impact badge + date */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: impact.color,
              background: impact.bg,
              padding: "3px 8px",
              borderRadius: 999,
              letterSpacing: "0.05em",
            }}
          >
            {impact.label}
          </span>
          {action && (
            <span
              style={{
                fontSize: 10,
                fontWeight: 600,
                color: action.color,
                background: action.bg,
                padding: "3px 8px",
                borderRadius: 999,
              }}
            >
              {action.label}
            </span>
          )}
          {item.discovered_at && (
            <span style={{ fontSize: 11, color: "var(--color-text-subtle)", marginLeft: "auto" }}>
              {new Date(item.discovered_at).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
                year: "numeric",
              })}
            </span>
          )}
        </div>

        {/* Title */}
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600, lineHeight: 1.35 }}>
          {item.source_url ? (
            <a
              href={item.source_url}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: "var(--color-text)", textDecoration: "none" }}
              onMouseEnter={(e) => (e.currentTarget.style.color = "var(--color-primary)")}
              onMouseLeave={(e) => (e.currentTarget.style.color = "var(--color-text)")}
            >
              {item.title}
              <svg
                style={{ display: "inline-block", marginLeft: 4, verticalAlign: -1 }}
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
              >
                <path d="M7 17 17 7M9 7h8v8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </a>
          ) : (
            item.title
          )}
        </h3>

        {/* Summary */}
        <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6, color: "var(--color-text-muted)" }}>
          {item.summary}
        </p>

        {/* Impact reasoning */}
        {item.impact_reasoning && (
          <div
            style={{
              fontSize: 13,
              color: "var(--color-text-muted)",
              borderLeft: "3px solid var(--color-border)",
              paddingLeft: 10,
              fontStyle: "italic",
              lineHeight: 1.5,
            }}
          >
            {item.impact_reasoning}
          </div>
        )}

        {/* Topics */}
        {item.topics && item.topics.length > 0 && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 2 }}>
            {item.topics.map((tag) => (
              <span
                key={tag}
                style={{
                  fontSize: 11,
                  background: "#f1f5f9",
                  color: "#475569",
                  padding: "3px 10px",
                  borderRadius: 999,
                  fontWeight: 500,
                }}
              >
                {formatTopic(tag)}
              </span>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}
