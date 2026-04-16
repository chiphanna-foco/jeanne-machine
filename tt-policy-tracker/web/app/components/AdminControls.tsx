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
}

const ACTIONS: Action[] = [
  {
    key: "ingest",
    label: "Pull New Data",
    description: "Fetch last 30 days of bills and regulations from Congress, state legislatures, and federal agencies.",
    path: "/admin/run-pipeline?days_back=30&batch_size=50",
  },
  {
    key: "enrich",
    label: "Run AI Analysis",
    description: "Run Haiku + Sonnet on un-processed raw documents. Use this after pulling new data.",
    path: "/admin/run-enrich?batch_size=50&min_confidence=0.5",
  },
  {
    key: "refresh-laws",
    label: "Refresh Current Laws",
    description: "Regenerate the jurisdiction × topic law repository from current policy items.",
    path: "/admin/refresh-laws?min_items=1&max_pairs=50",
  },
  {
    key: "weekly-full",
    label: "Run Full Weekly Pipeline",
    description: "Ingest → enrich → refresh laws → Slack digest. This is what the Friday cron runs.",
    path: "/admin/cron-weekly-full",
    confirmText: "This runs the complete weekly pipeline (ingest + enrich + laws + Slack). Continue?",
  },
  {
    key: "slack",
    label: "Send Slack Digest",
    description: "Send a weekly digest to the configured Slack channel.",
    path: "/admin/send-slack-digest?frequency=weekly&days_back=7",
  },
];

function formatTimestamp(iso: string | null): string {
  if (!iso) return "never";
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

export function AdminControls() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fetchStatus = async () => {
    try {
      const resp = await fetch("/admin/pipeline-status");
      if (resp.ok) {
        const data = await resp.json();
        setStatus(data);
      }
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    if (!open) return;
    fetchStatus();
    const interval = setInterval(fetchStatus, 4000);
    return () => clearInterval(interval);
  }, [open]);

  const trigger = async (action: Action) => {
    if (action.confirmText && !confirm(action.confirmText)) return;
    setBusy(true);
    setMessage(null);
    try {
      const resp = await fetch(action.path);
      const data = await resp.json();
      if (resp.ok) {
        setMessage(`${action.label}: ${data.message || "Started"}`);
      } else {
        setMessage(`${action.label} failed: ${data.error || resp.statusText}`);
      }
    } catch (err) {
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
        style={{
          position: "fixed",
          bottom: 16,
          right: 16,
          padding: "10px 16px",
          background: "#1a56db",
          color: "#fff",
          border: "none",
          borderRadius: 24,
          fontSize: 13,
          fontWeight: 600,
          cursor: "pointer",
          boxShadow: "0 4px 12px rgba(26,86,219,0.3)",
          zIndex: 40,
        }}
      >
        Admin
      </button>
    );
  }

  const running = status?.running;
  const lastResult = status?.last_result;

  return (
    <div
      style={{
        position: "fixed",
        bottom: 16,
        right: 16,
        width: 360,
        maxHeight: "80vh",
        overflowY: "auto",
        background: "#fff",
        borderRadius: 12,
        boxShadow: "0 8px 32px rgba(0,0,0,0.18)",
        zIndex: 40,
        padding: 16,
        border: "1px solid #e5e7eb",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700 }}>Admin Controls</h3>
        <button
          onClick={() => setOpen(false)}
          style={{
            background: "transparent",
            border: "none",
            fontSize: 18,
            cursor: "pointer",
            color: "#9ca3af",
            padding: 0,
          }}
        >
          ×
        </button>
      </div>

      <div
        style={{
          background: running ? "#fef3c7" : "#f3f4f6",
          borderRadius: 6,
          padding: "8px 10px",
          fontSize: 11,
          color: running ? "#92400e" : "#4b5563",
          marginBottom: 12,
        }}
      >
        <div style={{ fontWeight: 600 }}>
          {running ? "🟡 Pipeline running..." : "⚪ Idle"}
        </div>
        <div style={{ fontSize: 10, marginTop: 2 }}>Last run: {formatTimestamp(status?.last_run ?? null)}</div>
        {lastResult && !running && (
          <pre
            style={{
              margin: "6px 0 0 0",
              fontSize: 10,
              lineHeight: 1.4,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              maxHeight: 100,
              overflowY: "auto",
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
            borderRadius: 6,
            padding: "8px 10px",
            fontSize: 12,
            marginBottom: 12,
          }}
        >
          {message}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {ACTIONS.map((action) => (
          <button
            key={action.key}
            onClick={() => trigger(action)}
            disabled={busy || running}
            style={{
              textAlign: "left",
              padding: "10px 12px",
              background: "#f9fafb",
              border: "1px solid #e5e7eb",
              borderRadius: 8,
              cursor: busy || running ? "not-allowed" : "pointer",
              opacity: busy || running ? 0.5 : 1,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600, color: "#1f2937" }}>{action.label}</div>
            <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2, lineHeight: 1.4 }}>
              {action.description}
            </div>
          </button>
        ))}
      </div>

      <div style={{ fontSize: 10, color: "#9ca3af", marginTop: 12, lineHeight: 1.4 }}>
        Typical flow: <strong>Pull New Data</strong> → wait for idle → <strong>Run AI Analysis</strong> → <strong>Refresh Current Laws</strong>.
        Or click <strong>Run Full Weekly Pipeline</strong> to do all of it at once.
      </div>
    </div>
  );
}
