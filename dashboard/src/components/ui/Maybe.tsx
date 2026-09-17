import { formatValue, type MeasureKind } from "./Measure";

/** A plain nullable number (percentile, confidence): formatted, or a muted fallback. */
export function Maybe({ v, kind = "num", digits, fallback = "n/a", reason }: { v: number | null | undefined; kind?: MeasureKind; digits?: number; fallback?: string; reason?: string }) {
  if (v === null || v === undefined || Number.isNaN(v)) {
    return (
      <span className="measure--na" title={reason ?? "not available"}>
        {fallback}
      </span>
    );
  }
  return <span className="measure">{formatValue(v, kind, digits)}</span>;
}
