import { Maybe } from "./Maybe";

export function Percentile({ value, label }: { value: number | null | undefined; label?: string }) {
  if (value === null || value === undefined) return <Maybe v={value} />;
  const pct = Math.max(0, Math.min(100, value));
  return (
    <span className="pct" title={label ? `${label}: P${Math.round(pct)}` : `P${Math.round(pct)}`}>
      <span className="bar" aria-hidden="true">
        <span style={{ width: `${pct}%` }} />
      </span>
      <span className="small">P{Math.round(pct)}</span>
    </span>
  );
}
