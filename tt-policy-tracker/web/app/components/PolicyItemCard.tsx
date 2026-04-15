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

const IMPACT_COLORS: Record<string, string> = {
  high: "#dc2626",
  med: "#f59e0b",
  low: "#10b981",
};

const IMPACT_LABELS: Record<string, string> = {
  high: "HIGH",
  med: "MED",
  low: "LOW",
};

const ACTION_LABELS: Record<string, { label: string; color: string }> = {
  urgent: { label: "Urgent", color: "#dc2626" },
  monitor: { label: "Monitor", color: "#f59e0b" },
  inform: { label: "Inform", color: "#6b7280" },
};

export function PolicyItemCard({ item }: { item: PolicyItem }) {
  const borderColor = IMPACT_COLORS[item.impact_score] || "#e5e7eb";

  return (
    <div
      style={{
        background: "#fff",
        borderRadius: 8,
        borderLeft: `4px solid ${borderColor}`,
        padding: "16px 20px",
        boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        <span
          style={{
            display: "inline-block",
            fontSize: 10,
            fontWeight: 700,
            color: "#fff",
            background: borderColor,
            padding: "2px 8px",
            borderRadius: 4,
            flexShrink: 0,
            marginTop: 2,
          }}
        >
          {IMPACT_LABELS[item.impact_score]}
        </span>

        <div style={{ flex: 1 }}>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>
            {item.source_url ? (
              <a
                href={item.source_url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: "#1a56db", textDecoration: "none" }}
              >
                {item.title}
              </a>
            ) : (
              item.title
            )}
          </h3>

          <p style={{ margin: "6px 0", fontSize: 14, lineHeight: 1.5, color: "#374151" }}>
            {item.summary}
          </p>

          {item.impact_reasoning && (
            <p style={{ margin: "4px 0", fontSize: 13, color: "#6b7280", fontStyle: "italic" }}>
              {item.impact_reasoning}
            </p>
          )}

          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
            {item.action_needed && ACTION_LABELS[item.action_needed] && (
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: ACTION_LABELS[item.action_needed].color,
                  border: `1px solid ${ACTION_LABELS[item.action_needed].color}`,
                  padding: "1px 6px",
                  borderRadius: 4,
                }}
              >
                {ACTION_LABELS[item.action_needed].label}
              </span>
            )}

            {item.topics?.map((tag) => (
              <span
                key={tag}
                style={{
                  fontSize: 11,
                  background: "#e0e7ff",
                  color: "#3730a3",
                  padding: "2px 8px",
                  borderRadius: 12,
                }}
              >
                {tag.replace(/_/g, " ")}
              </span>
            ))}

            {item.discovered_at && (
              <span style={{ fontSize: 11, color: "#9ca3af", marginLeft: "auto" }}>
                {new Date(item.discovered_at).toLocaleDateString()}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
