"use client";

import Link from "next/link";

interface HeaderProps {
  subtitle?: string;
}

export function Header({ subtitle }: HeaderProps) {
  return (
    <header
      style={{
        position: "relative",
        overflow: "hidden",
        background: "linear-gradient(135deg, #0f0724 0%, #1e1b4b 40%, #0b1120 100%)",
        color: "#fff",
        padding: "36px 24px 60px",
        marginBottom: -32,
      }}
    >
      {/* Animated gradient blobs */}
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
          animation: "float1 14s ease-in-out infinite",
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
          animation: "float2 12s ease-in-out infinite",
        }}
      />
      <div
        style={{
          position: "absolute",
          bottom: -100,
          right: 120,
          width: 260,
          height: 260,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(245,158,11,0.22) 0%, transparent 65%)",
          pointerEvents: "none",
          animation: "float3 16s ease-in-out infinite",
        }}
      />

      {/* Grid overlay for tech-y texture */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)",
          backgroundSize: "40px 40px",
          pointerEvents: "none",
          maskImage: "radial-gradient(ellipse at center, black 20%, transparent 70%)",
          WebkitMaskImage: "radial-gradient(ellipse at center, black 20%, transparent 70%)",
        }}
      />

      <div
        style={{
          maxWidth: 1200,
          margin: "0 auto",
          position: "relative",
          zIndex: 1,
        }}
      >
        <Link
          href="/"
          style={{
            display: "inline-block",
            textDecoration: "none",
            color: "inherit",
          }}
        >
          {/* Status pill */}
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.15em",
              textTransform: "uppercase",
              color: "rgba(255,255,255,0.75)",
              background: "rgba(255,255,255,0.06)",
              border: "1px solid rgba(255,255,255,0.1)",
              padding: "4px 12px",
              borderRadius: 999,
              marginBottom: 14,
              backdropFilter: "blur(6px)",
            }}
          >
            <span
              style={{
                display: "inline-block",
                width: 6,
                height: 6,
                borderRadius: "50%",
                background: "#22d3ee",
                boxShadow: "0 0 8px rgba(34,211,238,0.8)",
                animation: "livePulse 1.6s ease-in-out infinite",
              }}
            />
            Live · AI-powered · Updated weekly
          </div>

          {/* Wordmark */}
          <h1
            style={{
              margin: 0,
              fontSize: "clamp(38px, 6vw, 64px)",
              fontWeight: 900,
              lineHeight: 0.95,
              letterSpacing: "-0.04em",
              color: "#fff",
              fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, sans-serif",
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
            <span
              style={{
                color: "#f59e0b",
                marginLeft: 2,
                animation: "cursorBlink 1.1s steps(1) infinite",
              }}
            >
              _
            </span>
          </h1>

          {/* Tagline */}
          <p
            style={{
              margin: "12px 0 0",
              fontSize: 15,
              fontWeight: 500,
              color: "rgba(255,255,255,0.75)",
              letterSpacing: "-0.01em",
              maxWidth: 560,
              lineHeight: 1.5,
            }}
          >
            {subtitle || "She reads every rental housing law in America so you don't have to."}
          </p>
        </Link>
      </div>

      <style>{`
        @keyframes float1 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(-30px, 20px) scale(1.1); }
        }
        @keyframes float2 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(40px, -20px) scale(0.9); }
        }
        @keyframes float3 {
          0%, 100% { transform: translate(0, 0) scale(1); }
          50% { transform: translate(-20px, -30px) scale(1.15); }
        }
        @keyframes livePulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        @keyframes cursorBlink {
          0%, 50% { opacity: 1; }
          51%, 100% { opacity: 0; }
        }
      `}</style>
    </header>
  );
}
