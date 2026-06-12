"use client";

const TOPICS = [
  { value: "", label: "All Topics" },
  { value: "landlord_tenant_law", label: "Landlord-Tenant Law" },
  { value: "security_deposit", label: "Security Deposit" },
  { value: "eviction", label: "Eviction" },
  { value: "source_of_income", label: "Source of Income" },
  { value: "rental_registration", label: "Rental Registration" },
  { value: "screening_restrictions", label: "Screening Restrictions" },
  { value: "application_fee_limit", label: "Application Fee Limit" },
  { value: "rent_control", label: "Rent Control" },
  { value: "habitability", label: "Habitability" },
  { value: "fair_housing", label: "Fair Housing" },
];

const IMPACTS = [
  { value: "", label: "All Impact" },
  { value: "high", label: "High" },
  { value: "med", label: "Medium" },
  { value: "low", label: "Low" },
];

const inputStyle: React.CSSProperties = {
  padding: "9px 12px",
  borderRadius: 8,
  border: "1px solid var(--color-border-strong)",
  fontSize: 13,
  background: "#fff",
  color: "var(--color-text)",
  fontFamily: "inherit",
  fontWeight: 500,
  outline: "none",
  transition: "border-color 160ms ease, box-shadow 160ms ease",
};

const SORTS = [
  { value: "", label: "Sort: Newest first" },
  { value: "effective", label: "Sort: Goes into law soonest" },
];

interface FiltersProps {
  filters: { topic?: string; impact?: string; state?: string; sort?: string };
  onChange: (filters: { topic?: string; impact?: string; state?: string; sort?: string }) => void;
}

export function Filters({ filters, onChange }: FiltersProps) {
  const hasFilters = filters.topic || filters.impact || filters.state;

  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        marginBottom: 16,
        flexWrap: "wrap",
        alignItems: "center",
      }}
    >
      <span style={{ fontSize: 12, color: "var(--color-text-subtle)", fontWeight: 600 }}>
        Filter:
      </span>

      <select
        style={{ ...inputStyle, cursor: "pointer" }}
        value={filters.topic || ""}
        onChange={(e) => onChange({ ...filters, topic: e.target.value || undefined })}
      >
        {TOPICS.map((t) => (
          <option key={t.value} value={t.value}>
            {t.label}
          </option>
        ))}
      </select>

      <select
        style={{ ...inputStyle, cursor: "pointer" }}
        value={filters.impact || ""}
        onChange={(e) => onChange({ ...filters, impact: e.target.value || undefined })}
      >
        {IMPACTS.map((i) => (
          <option key={i.value} value={i.value}>
            {i.label}
          </option>
        ))}
      </select>

      <input
        type="text"
        placeholder="State code (e.g. CO)"
        value={filters.state || ""}
        onChange={(e) => onChange({ ...filters, state: e.target.value.toUpperCase() || undefined })}
        maxLength={2}
        style={{ ...inputStyle, width: 140 }}
      />

      <select
        style={{ ...inputStyle, cursor: "pointer" }}
        value={filters.sort || ""}
        onChange={(e) => onChange({ ...filters, sort: e.target.value || undefined })}
      >
        {SORTS.map((s) => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </select>

      {hasFilters && (
        <button
          onClick={() => onChange({ sort: filters.sort })}
          style={{
            padding: "6px 12px",
            fontSize: 12,
            fontWeight: 600,
            color: "var(--color-text-muted)",
            background: "transparent",
            border: "1px solid var(--color-border)",
            borderRadius: 8,
            cursor: "pointer",
          }}
        >
          Clear
        </button>
      )}
    </div>
  );
}
