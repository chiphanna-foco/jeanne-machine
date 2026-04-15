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

const selectStyle: React.CSSProperties = {
  padding: "8px 12px",
  borderRadius: 6,
  border: "1px solid #d1d5db",
  fontSize: 13,
  background: "#fff",
  color: "#374151",
  cursor: "pointer",
};

interface FiltersProps {
  filters: { topic?: string; impact?: string; state?: string };
  onChange: (filters: { topic?: string; impact?: string; state?: string }) => void;
}

export function Filters({ filters, onChange }: FiltersProps) {
  return (
    <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
      <select
        style={selectStyle}
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
        style={selectStyle}
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
        placeholder="State code (e.g. CO, OH)"
        value={filters.state || ""}
        onChange={(e) => onChange({ ...filters, state: e.target.value || undefined })}
        style={{
          ...selectStyle,
          width: 180,
        }}
      />
    </div>
  );
}
