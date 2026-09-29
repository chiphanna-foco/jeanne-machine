"use client";

import { useState } from "react";

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
  feedback?: "up" | "down" | "watching" | null;
}

const VOTES: { key: "up" | "down" | "watching"; emoji: string; title: string }[] = [
  { key: "up", emoji: "👍", title: "Relevant — keep showing bills like this" },
  { key: "down", emoji: "👎", title: "Noise — hide this bill" },
  { key: "watching", emoji: "👀", title: "Watching this one" },
];

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

  const [fb, setFb] = useState<PolicyItem["feedback"]>(item.feedback ?? null);
  const [busy, setBusy] = useState(false);

  async function vote(label: "up" | "down" | "watching") {
    if (busy) return;
    const prev = fb;
    setFb(label); // optimistic
    setBusy(true);
    try {
      const r = await fetch(`/backend/api/items/${item.id}/feedback?label=${label}`, { method: "POST" });
      if (!r.ok) throw new Error(`API ${r.status}`);
    } catch {
      setFb(prev); // revert on failure
    } finally {
      setBusy(false);
    }
  }

  // "Draft blog post": POST starts the drafter on Railway (or returns the
  // existing draft), then poll GET until the draft exists.
  const [draftState, setDraftState] = useState<"idle" | "drafting" | "ready" | "failed">("idle");
  const [draftId, setDraftId] = useState<number | null>(null);
  const [draftNote, setDraftNote] = useState<string | null>(null);

  async function pollDraft(attempt = 0) {
    if (attempt > 60) {
      setDraftState("failed");
      setDraftNote("Still drafting after 3 minutes. Check Content Drafts later.");
      return;
    }
    try {
      const r = await fetch(`/backend/api/items/${item.id}/drafts`, { cache: "no-store" });
      const data = await r.json();
      if (r.ok && data.status === "exists") {
        setDraftId(data.draft.id);
        setDraftState("ready");
        return;
      }
      if (!r.ok || data.status === "failed" || data.status === "none") {
        setDraftState("failed");
        setDraftNote(data.error || `Draft failed (${r.status})`);
        return;
      }
    } catch {
      // transient network error: keep polling
    }
    setTimeout(() => pollDraft(attempt + 1), 3000);
  }

  async function startDraft() {
    if (draftState === "drafting") return;
    setDraftState("drafting");
    setDraftNote(null);
    try {
      const r = await fetch(`/backend/api/items/${item.id}/drafts`, { method: "POST" });
      const data = await r.json();
      if (r.status === 200 && data.status === "exists") {
        setDraftId(data.draft.id);
        setDraftNote(data.note || null);
        setDraftState("ready");
      } else if (r.status === 202) {
        setTimeout(() => pollDraft(0), 3000);
      } else if (r.status === 429) {
        setDraftState("failed");
        setDraftNote("Busy, try again in a minute");
      } else {
        setDraftState("failed");
        setDraftNote(data.error || `Draft failed (${r.status})`);
      }
    } catch {
      setDraftState("failed");
      setDraftNote("Network error");
    }
  }

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
          {item.effective_date && (
            <span
              title="Date this goes into law"
              style={{
                fontSize: 10,
                fontWeight: 600,
                color: "#7c3aed",
                background: "#f5f3ff",
                padding: "3px 8px",
                borderRadius: 999,
              }}
            >
              📅 In law:{" "}
              {new Date(item.effective_date).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
                year: "numeric",
              })}
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
        <h3 style={{ margin: 0, fontSize: 17, fontWeight: 600, lineHeight: 1.35 }}>
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
        <p style={{ margin: 0, fontSize: 15, lineHeight: 1.65, color: "var(--color-text-muted)" }}>
          {item.summary}
        </p>

        {/* Impact reasoning */}
        {item.impact_reasoning && (
          <div
            style={{
              fontSize: 14,
              color: "var(--color-text-muted)",
              borderLeft: "3px solid var(--color-border)",
              paddingLeft: 12,
              fontStyle: "italic",
              lineHeight: 1.6,
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

        {/* Feedback: 👍 relevant / 👎 noise / 👀 watching */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            flexWrap: "wrap",
            gap: 6,
            marginTop: 4,
            paddingTop: 10,
            borderTop: "1px solid var(--color-border)",
          }}
        >
          {VOTES.map((v) => {
            const active = fb === v.key;
            return (
              <button
                key={v.key}
                title={v.title}
                disabled={busy}
                onClick={() => vote(v.key)}
                style={{
                  fontSize: 14,
                  lineHeight: 1,
                  padding: "5px 10px",
                  borderRadius: 8,
                  cursor: busy ? "default" : "pointer",
                  border: `1px solid ${active ? "var(--color-primary)" : "var(--color-border)"}`,
                  background: active ? "var(--color-primary-soft, #f5f3ff)" : "#fff",
                  filter: active ? "none" : "grayscale(0.4)",
                  opacity: busy ? 0.6 : 1,
                  transition: "all 140ms ease",
                }}
              >
                {v.emoji}
              </button>
            );
          })}
          {fb === "down" && (
            <span style={{ fontSize: 11, color: "var(--color-text-subtle)", marginLeft: 2 }}>
              Hidden on next load
            </span>
          )}
          <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
            {draftNote && (
              <span style={{ fontSize: 11, color: "var(--color-text-subtle)" }}>{draftNote}</span>
            )}
            {draftState === "ready" && draftId !== null ? (
              <a
                href={`/drafts?highlight=${draftId}`}
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  padding: "5px 10px",
                  borderRadius: 8,
                  border: "1px solid var(--color-primary)",
                  color: "var(--color-primary)",
                  textDecoration: "none",
                  whiteSpace: "nowrap",
                }}
              >
                View draft
              </a>
            ) : (
              <button
                title="Write a blog post draft from this item"
                disabled={draftState === "drafting"}
                onClick={startDraft}
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  padding: "5px 10px",
                  borderRadius: 8,
                  cursor: draftState === "drafting" ? "default" : "pointer",
                  border: "1px solid var(--color-border)",
                  background: "#fff",
                  color: "var(--color-text)",
                  opacity: draftState === "drafting" ? 0.7 : 1,
                  whiteSpace: "nowrap",
                }}
              >
                {draftState === "drafting"
                  ? "Drafting\u2026"
                  : draftState === "failed"
                    ? "Retry draft"
                    : "Draft blog post"}
              </button>
            )}
          </span>
        </div>
      </div>
    </article>
  );
}
