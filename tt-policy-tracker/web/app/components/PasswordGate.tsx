"use client";

import { useEffect, useState } from "react";

const PASSWORD_STORAGE_KEY = "jm_site_password";

type GateState = "checking" | "required" | "unlocked" | "not-required";

export function PasswordGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<GateState>("checking");
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const verify = async (candidate: string): Promise<boolean> => {
    try {
      const resp = await fetch(
        `/api/auth/verify?token=${encodeURIComponent(candidate)}`,
        { cache: "no-store" }
      );
      if (!resp.ok) return false;
      const data = await resp.json();
      if (data.auth_required === false) {
        setState("not-required");
        return true;
      }
      return !!data.valid;
    } catch {
      return false;
    }
  };

  // On mount, try stored password
  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(PASSWORD_STORAGE_KEY);
    if (!stored) {
      verify("").then((ok) => {
        setState(ok ? "not-required" : "required");
      });
      return;
    }
    verify(stored).then((ok) => {
      if (ok) setState("unlocked");
      else {
        window.localStorage.removeItem(PASSWORD_STORAGE_KEY);
        setState("required");
      }
    });
  }, []);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input) return;
    setBusy(true);
    setError(null);
    const ok = await verify(input);
    setBusy(false);
    if (ok) {
      if (typeof window !== "undefined") {
        window.localStorage.setItem(PASSWORD_STORAGE_KEY, input);
      }
      setState("unlocked");
    } else {
      setError("Nope, try again.");
      setInput("");
    }
  };

  if (state === "checking") {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg, #0f0724 0%, #1e1b4b 50%, #0b1120 100%)",
        }}
      >
        <div style={{ color: "rgba(255,255,255,0.6)", fontSize: 14 }}>Loading...</div>
      </div>
    );
  }

  if (state === "unlocked" || state === "not-required") {
    return <>{children}</>;
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        background: "linear-gradient(135deg, #0f0724 0%, #1e1b4b 40%, #0b1120 100%)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Floating gradient blobs for ambience */}
      <div
        style={{
          position: "absolute",
          top: -140,
          right: -100,
          width: 420,
          height: 420,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(236,72,153,0.35) 0%, transparent 65%)",
          pointerEvents: "none",
          animation: "gateFloat1 14s ease-in-out infinite",
        }}
      />
      <div
        style={{
          position: "absolute",
          top: -80,
          left: -60,
          width: 320,
          height: 320,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(6,182,212,0.28) 0%, transparent 65%)",
          pointerEvents: "none",
          animation: "gateFloat2 12s ease-in-out infinite",
        }}
      />

      <form
        onSubmit={onSubmit}
        style={{
          position: "relative",
          zIndex: 1,
          width: "100%",
          maxWidth: 440,
          background: "rgba(255,255,255,0.04)",
          backdropFilter: "blur(14px)",
          border: "1px solid rgba(255,255,255,0.1)",
          borderRadius: 18,
          padding: "36px 32px",
          boxShadow: "0 30px 80px rgba(0,0,0,0.35)",
          textAlign: "center",
        }}
      >
        <h1
          style={{
            margin: 0,
            fontSize: 42,
            fontWeight: 900,
            lineHeight: 1,
            letterSpacing: "-0.04em",
            color: "#fff",
          }}
        >
          <span
            style={{
              background: "linear-gradient(135deg, #f9a8d4 0%, #ec4899 50%, #a855f7 100%)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            Jeanne
          </span>{" "}
          <span
            style={{
              background: "linear-gradient(135deg, #67e8f9 0%, #06b6d4 50%, #f59e0b 100%)",
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
              backgroundClip: "text",
            }}
          >
            Machine
          </span>
        </h1>
        <p
          style={{
            margin: "14px 0 26px",
            fontSize: 14,
            color: "rgba(255,255,255,0.65)",
            lineHeight: 1.55,
          }}
        >
          Who goes there? Drop the password to come in.
        </p>

        <input
          type="password"
          autoFocus
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Password"
          style={{
            width: "100%",
            padding: "12px 14px",
            fontSize: 15,
            fontWeight: 500,
            background: "rgba(255,255,255,0.08)",
            border: "1px solid rgba(255,255,255,0.15)",
            borderRadius: 10,
            color: "#fff",
            outline: "none",
            boxSizing: "border-box",
            fontFamily: "inherit",
            letterSpacing: "0.02em",
          }}
          onFocus={(e) => {
            e.currentTarget.style.borderColor = "rgba(236,72,153,0.6)";
            e.currentTarget.style.background = "rgba(255,255,255,0.12)";
          }}
          onBlur={(e) => {
            e.currentTarget.style.borderColor = "rgba(255,255,255,0.15)";
            e.currentTarget.style.background = "rgba(255,255,255,0.08)";
          }}
        />

        {error && (
          <div
            style={{
              marginTop: 12,
              fontSize: 12,
              color: "#fca5a5",
              fontWeight: 500,
            }}
          >
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={!input || busy}
          style={{
            marginTop: 18,
            width: "100%",
            padding: "12px 16px",
            fontSize: 14,
            fontWeight: 700,
            color: "#fff",
            background: input && !busy
              ? "linear-gradient(135deg, #ec4899 0%, #a855f7 50%, #06b6d4 100%)"
              : "rgba(255,255,255,0.1)",
            border: "none",
            borderRadius: 10,
            cursor: input && !busy ? "pointer" : "not-allowed",
            letterSpacing: "0.02em",
            transition: "transform 160ms ease, box-shadow 160ms ease",
            boxShadow: input && !busy ? "0 10px 30px rgba(236,72,153,0.35)" : "none",
          }}
          onMouseEnter={(e) => {
            if (input && !busy) e.currentTarget.style.transform = "translateY(-1px)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.transform = "translateY(0)";
          }}
        >
          {busy ? "Checking..." : "Enter"}
        </button>

        <div
          style={{
            marginTop: 22,
            fontSize: 10,
            color: "rgba(255,255,255,0.35)",
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            fontWeight: 600,
          }}
        >
          Internal TurboTenant Tool
        </div>
      </form>

      <style>{`
        @keyframes gateFloat1 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(-30px, 20px) scale(1.1); }
        }
        @keyframes gateFloat2 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(40px, -20px) scale(0.9); }
        }
      `}</style>
    </div>
  );
}

// Export a helper that other components can use to grab the stored password
export function getStoredPassword(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(PASSWORD_STORAGE_KEY) || "";
}
