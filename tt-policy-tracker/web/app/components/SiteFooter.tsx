// Data-source attribution footer. Required for a PUBLIC deployment:
// LegiScan's API is CC BY 4.0 (attribution to "LegiScan LLC" + license link is
// mandatory) and CourtListener/Free Law Project content is CC BY (credit
// required). See docs/DATA_SOURCE_LICENSING.md for the full review. The other
// sources are US public domain / public-domain-dedicated — credited here as a
// courtesy. No government logos/seals are used and no endorsement is implied.

const SOURCES: { name: string; href: string; note?: string }[] = [
  { name: "LegiScan", href: "https://legiscan.com/", note: "CC BY 4.0" },
  { name: "Open States / Plural", href: "https://openstates.org/" },
  { name: "Congress.gov", href: "https://www.congress.gov/" },
  { name: "Federal Register", href: "https://www.federalregister.gov/" },
  { name: "CourtListener / Free Law Project", href: "https://www.courtlistener.com/" },
  { name: "U.S. Bureau of Labor Statistics", href: "https://www.bls.gov/" },
  { name: "Washington State Legislature", href: "https://leg.wa.gov/" },
  { name: "Legistar (municipal records)", href: "https://webapi.legistar.com/" },
];

const linkStyle: React.CSSProperties = {
  color: "var(--color-text-muted)",
  textDecoration: "none",
  borderBottom: "1px solid var(--color-border)",
};

export function SiteFooter() {
  return (
    <footer
      style={{
        maxWidth: 1000,
        margin: "0 auto",
        padding: "28px 24px 48px",
        borderTop: "1px solid var(--color-border)",
        fontSize: 12,
        lineHeight: 1.7,
        color: "var(--color-text-subtle)",
      }}
    >
      <div style={{ fontWeight: 700, color: "var(--color-text-muted)", marginBottom: 6 }}>
        Data sources
      </div>
      <div style={{ marginBottom: 10 }}>
        Legislative data via{" "}
        <a href="https://legiscan.com/" target="_blank" rel="noopener noreferrer" style={linkStyle}>
          LegiScan
        </a>{" "}
        (
        <a
          href="https://creativecommons.org/licenses/by/4.0/"
          target="_blank"
          rel="noopener noreferrer"
          style={linkStyle}
        >
          CC BY 4.0
        </a>
        ). Court data via{" "}
        <a
          href="https://www.courtlistener.com/"
          target="_blank"
          rel="noopener noreferrer"
          style={linkStyle}
        >
          CourtListener
        </a>{" "}
        (Free Law Project). Additional data:{" "}
        {SOURCES.filter(
          (s) => !s.name.startsWith("LegiScan") && !s.name.startsWith("CourtListener"),
        ).map((s, i, arr) => (
          <span key={s.name}>
            <a href={s.href} target="_blank" rel="noopener noreferrer" style={linkStyle}>
              {s.name}
            </a>
            {i < arr.length - 1 ? ", " : "."}
          </span>
        ))}
      </div>
      <div>
        Summaries are AI-generated, may be inaccurate or incomplete, and are{" "}
        <strong>not legal advice</strong>. Links point to the official source
        documents. Jeanne Machine is not affiliated with, and no endorsement is
        implied by, any listed source.
      </div>
    </footer>
  );
}
