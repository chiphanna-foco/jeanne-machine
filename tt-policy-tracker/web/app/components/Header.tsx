"use client";

import Link from "next/link";

interface HeaderProps {
  subtitle?: string;
}

export function Header({ subtitle }: HeaderProps) {
  return (
    <header
      className="hero-gradient"
      style={{
        position: "relative",
        overflow: "hidden",
        color: "#fff",
        padding: "28px 24px 56px",
        marginBottom: -32,
      }}
    >
      {/* Background glow accent */}
      <div
        style={{
          position: "absolute",
          top: -100,
          right: -80,
          width: 320,
          height: 320,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(6,182,212,0.18) 0%, transparent 60%)",
          pointerEvents: "none",
        }}
      />
      <div
        style={{
          position: "absolute",
          bottom: -60,
          left: -40,
          width: 200,
          height: 200,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(245,158,11,0.08) 0%, transparent 60%)",
          pointerEvents: "none",
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
            display: "flex",
            alignItems: "center",
            gap: 14,
            textDecoration: "none",
            color: "inherit",
            width: "fit-content",
          }}
        >
          <div
            style={{
              width: 52,
              height: 52,
              background: "rgba(255,255,255,0.08)",
              borderRadius: 12,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              border: "1px solid rgba(255,255,255,0.12)",
              backdropFilter: "blur(4px)",
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/logo.svg" alt="Jeanne Machine" width={40} height={40} />
          </div>
          <div>
            <h1
              style={{
                margin: 0,
                fontSize: 22,
                fontWeight: 700,
                letterSpacing: "-0.02em",
                color: "#fff",
              }}
            >
              Jeanne Machine
            </h1>
            <p
              style={{
                margin: "2px 0 0",
                fontSize: 12,
                color: "rgba(255,255,255,0.7)",
                letterSpacing: "0.02em",
              }}
            >
              {subtitle || "Rental housing policy intelligence"}
            </p>
          </div>
        </Link>
      </div>
    </header>
  );
}
