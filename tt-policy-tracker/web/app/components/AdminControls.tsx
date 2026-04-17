"use client";

import { useEffect, useState } from "react";

interface PipelineStatus {
  running: boolean;
  last_run: string | null;
  last_result: Record<string, unknown> | null;
}

interface Action {
  key: string;
  label: string;
  description: string;
  path: string;
  confirmText?: string;
  icon: string;
}

const ACTIONS: Action[] = [
  {
    key: "ingest",
    label: "Pull New Data",
    description: "Fetch last 30 days from Congress, state legislatures, and federal agencies.",
    path: "/admin/run-pipeline?days_back=30&batch_size=50",
    icon: "🔄",
  },
  {
    key: "enrich",
    label: "Run AI Analysis",
    description: "Run Haiku + Sonnet on un-processed raw documents.",
    path: "/admin/run-enrich?batch_size=50&min_confidence=0.5",
    icon: "🧠",
  },
  {
    key: "refresh-laws",
    label: "Refresh Current Laws",
    description: "Regenerate the jurisdiction × topic law repository.",
    path: "/admin/refresh-laws?min_items=1&max_pairs=50",
    icon: "📚",
  },
  {
    key: "weekly-full",
    label: "Run Full Weekly Pipeline",
    description: "Ingest → enrich → refresh laws → Slack. Matches Friday cron.",
    path: "/admin/cron-weekly-full",
    confirmText: "This runs the complete weekly pipeline (ingest + enrich + laws + Slack). Continue?",
    icon: "⚡",
  },
  {
    key: "slack",
    label: "Send Slack Digest",
    description: "Send a weekly digest to the configured Slack channel.",
    path: "/admin/send-slack-digest?frequency=weekly&days_back=7",
    icon: "💬",
  },
  {
    key: "drafts",
    label: "Generate Blog Drafts",
    description: "Create AI-written blog drafts from high-impact items.",
    path: "/admin/generate-drafts?min_impact=high&max_drafts=5",
    icon: "✍️",
  },
];

const TOKEN_STORAGE_KEY = "jm_admin_token";

function formatTimestamp(iso: string | null): string {
  if (!iso) return "never";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function appendToken(path: string, token: string): string {
  if (!token) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}token=${encodeURIComponent(token)}`;
}

export function AdminControls() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [token, setToken] = useState("");
  const [tokenInput, setTokenInput] = useState("");
  const [editingToken, setEditingToken] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const saved = window.localStorage.getItem(TOKEN_STORAGE_KEY) || "";
      setToken(saved);
      if (!saved) setEditingToken(true);
    }
  }, []);

  const saveToken = () => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, tokenInput);
    }
    setToken(tokenInput);
    setTokenInput("");
    setEditingToken(false);
    setMessage("Token saved. Stored locally in your browser.");
  };

  const clearToken = () => {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
    setToken("");
    setTokenInput("");
    setEditingToken(true);
  };

  const fetchStatus = async () => {
    try {
      const resp = await fetch(appendToken("/admin/pipeline-status", token));
      if (resp.ok) {
        const data = await resp.json();
        setStatus(data);
      }
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    if (!open || !token) return;
    fetchStatus();
    const interval = setInterval(fetchStatus, 4000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, token]);

  const trigger = async (action: Action) => {
    if (action.confirmText && !confirm(action.confirmText)) return;
    setBusy(true);
    setMessage(null);
    try {
      const resp = await fetch(appendToken(action.path, token));
      const data = await resp.json();
      if (resp.ok) {
        setMessage(`${action.label}: ${data.message || "Started"}`);
      } else if (resp.status === 403) {
        setMessage(`Token rejected. Update or clear it below.`);
        setEditingToken(true);
      } else {
        setMessage(`${action.label} failed: ${data.error || resp.statusText}`);
      }
    } catch {
      setMessage(`${action.label} failed: network error`);
    } finally {
      setBusy(false);
      fetchStatus();
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        aria-label="Open admin controls"
        style={{
          position: "fixed",
          bottom: 20,
          right: 20,
          padding: "10px 18px",
          background: "linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%)",
          color: "#fff",
          border: "none",
          borderRadius: 999,
          fontSize: 13,
          fontWeight: 600,
          cursor: "pointer",
          boxShadow: "0 8px 24px rgba(30,58,138,0.35)",
          zIndex: 40,
          display: "flex",
          alignItems: "center",
          gap: 8,
          transition: "transform 160ms ease",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.transform = "translateY(-2px)")}
        onMouseLeave={(e) => (e.currentTarget.style.transform = "translateY(0)")}
      >
        <span style={{ fontSize: 15 }}>⚙️</span> Admin
      </button>
    );
  }

  const running = status?.running;
  const lastResult = status?.last_result;
  const needsToken = !token;

  return (
    <div
      style={{
        position: "fixed",
        bottom: 20,
        right: 20,
        width: 380,
        maxHeight: "82vh",
        overflowY: "auto",
        background: "#fff",
        borderRadius: 14,
        boxShadow: "0 20px 50px rgba(15,23,42,0.2), 0 8px 16px rgba(15,23,42,0.08)",
        zIndex: 40,
        padding: 18,
        border: "1px solid var(--color-border)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 8,
              background: "linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#fff",
              fontSize: 14,
            }}
          >
            ⚙️
          </div>
          <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700 }}>Admin Controls</h3>
        </div>
        <button
          onClick={() => setOpen(false)}
          aria-label="Close"
          style={{
            background: "#f1f5f9",
            border: "none",
            width: 28,
            height: 28,
            borderRadius: 8,
            fontSize: 14,
            cursor: "pointer",
            color: "var(--color-text-muted)",
          }}
        >
          ×
        </button>
      </div>

      {/* Token management */}
      {(needsToken || editingToken) && (
        <div
          style={{
            background: needsToken ? "#fef3c7" : "#f9fafb",
            border: `1px solid ${needsToken ? "#fde68a" : "var(--color-border)"}`,
            borderRadius: 10,
            padding: "12px 14px",
            marginBottom: 14,
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 4, color: "#374151" }}>
            {needsToken ? "🔒 Admin token required" : "Update token"}
          </div>
          <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginBottom: 10, lineHeight: 1.4 }}>
            Paste your ADMIN_TOKEN. Stored locally in your browser only.
          </div>
          <input
            type="password"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            placeholder="ADMIN_TOKEN"
            style={{
              width: "100%",
              padding: "8px 10px",
              fontSize: 12,
              fontFamily: "var(--font-mono)",
              border: "1px solid var(--color-border-strong)",
              borderRadius: 6,
              boxSizing: "border-box",
              background: "#fff",
            }}
          />
          <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
            <button
              onClick={saveToken}
              disabled={!tokenInput}
              style={{
                padding: "6px 14px",
                fontSize: 12,
                fontWeight: 600,
                background: tokenInput ? "var(--color-primary)" : "#d1d5db",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                cursor: tokenInput ? "pointer" : "not-allowed",
              }}
            >
              Save
            </button>
            {!needsToken && (
              <button
                onClick={() => {
                  setEditingToken(false);
                  setTokenInput("");
                }}
                style={{
                  padding: "6px 12px",
                  fontSize: 12,
                  background: "transparent",
                  color: "var(--color-text-muted)",
                  border: "1px solid var(--color-border-strong)",
                  borderRadius: 6,
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
            )}
          </div>
        </div>
      )}

      {!needsToken && !editingToken && (
        <div
          style={{
            fontSize: 11,
            color: "var(--color-text-subtle)",
            marginBottom: 12,
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <span style={{ display: "flex", alignItems: "center", gap: 4, color: "var(--color-success)", fontWeight: 600 }}>
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--color-success)", display: "inline-block" }} />
            Authenticated
          </span>
          <button
            onClick={() => setEditingToken(true)}
            style={{ background: "transparent", border: "none", color: "var(--color-text-muted)", fontSize: 11, cursor: "pointer", textDecoration: "underline", padding: 0 }}
          >
            change
          </button>
          <button
            onClick={clearToken}
            style={{ background: "transparent", border: "none", color: "var(--color-danger)", fontSize: 11, cursor: "pointer", textDecoration: "underline", padding: 0 }}
          >
            clear
          </button>
        </div>
      )}

      {/* Status card */}
      <div
        style={{
          background: running ? "linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)" : "#f8fafc",
          borderRadius: 10,
          padding: "10px 14px",
          fontSize: 11,
          marginBottom: 14,
          border: `1px solid ${running ? "#fcd34d" : "var(--color-border)"}`,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ fontWeight: 700, color: running ? "#92400e" : "var(--color-text-muted)", display: "flex", alignItems: "center", gap: 6 }}>
            {running ? (
              <>
                <span
                  style={{
                    display: "inline-block",
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: "#d97706",
                    animation: "pulse 1.4s ease-in-out infinite",
                  }}
                />
                Pipeline running...
              </>
            ) : (
              <>
                <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "#94a3b8" }} />
                Idle
              </>
            )}
          </span>
          <span style={{ fontSize: 10, color: "var(--color-text-subtle)" }}>
            Last: {formatTimestamp(status?.last_run ?? null)}
          </span>
        </div>
        {lastResult && !running && (
          <pre
            style={{
              margin: "8px 0 0 0",
              fontSize: 10,
              lineHeight: 1.4,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              maxHeight: 100,
              overflowY: "auto",
              fontFamily: "var(--font-mono)",
              background: "rgba(255,255,255,0.6)",
              padding: 8,
              borderRadius: 6,
            }}
          >
            {JSON.stringify(lastResult, null, 2)}
          </pre>
        )}
      </div>

      {message && (
        <div
          style={{
            background: "#eff6ff",
            border: "1px solid #bfdbfe",
            color: "#1e40af",
            borderRadius: 8,
            padding: "8px 12px",
            fontSize: 12,
            marginBottom: 12,
            lineHeight: 1.5,
          }}
        >
          {message}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {ACTIONS.map((action) => (
          <button
            key={action.key}
            onClick={() => trigger(action)}
            disabled={busy || running || needsToken}
            style={{
              textAlign: "left",
              padding: "10px 12px",
              background: "#fff",
              border: "1px solid var(--color-border)",
              borderRadius: 10,
              cursor: busy || running || needsToken ? "not-allowed" : "pointer",
              opacity: busy || running || needsToken ? 0.4 : 1,
              display: "flex",
              alignItems: "center",
              gap: 10,
              transition: "background 160ms ease, border-color 160ms ease",
            }}
            onMouseEnter={(e) => {
              if (busy || running || needsToken) return;
              e.currentTarget.style.background = "#f8fafc";
              e.currentTarget.style.borderColor = "var(--color-primary)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "#fff";
              e.currentTarget.style.borderColor = "var(--color-border)";
            }}
          >
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                background: "#f1f5f9",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 16,
                flexShrink: 0,
              }}
            >
              {action.icon}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text)" }}>{action.label}</div>
              <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 1, lineHeight: 1.4 }}>
                {action.description}
              </div>
            </div>
          </button>
        ))}
      </div>

      <div style={{ fontSize: 10, color: "var(--color-text-subtle)", marginTop: 14, lineHeight: 1.5, paddingTop: 12, borderTop: "1px solid var(--color-border)" }}>
        Typical flow: <strong>Pull New Data</strong> → wait → <strong>Run AI Analysis</strong> → <strong>Refresh Laws</strong>.
        Or use <strong>Run Full Weekly Pipeline</strong> for everything at once.
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(1.2); }
        }
      `}</style>
    </div>
  );
}
