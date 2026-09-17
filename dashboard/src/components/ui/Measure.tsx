import type { Measure as MeasureT } from "../../api/types";
import { fmtCompact, fmtCompactKes, fmtInt, fmtKes, fmtNum, fmtPct, fmtPctPoints, fmtRatio } from "../../lib/format";
import { isKnown, statusLabel } from "../../lib/measure";

export type MeasureKind = "kes" | "pct" | "pctpoints" | "num" | "ratio" | "compact" | "compactkes" | "int" | "score";

export interface MeasureProps {
  m: MeasureT | null | undefined;
  kind?: MeasureKind;
  digits?: number;
  signed?: boolean;
  showReason?: boolean;
  className?: string;
}

export function formatValue(value: number, kind: MeasureKind, digits?: number, signed = false): string {
  switch (kind) {
    case "kes":
      return fmtKes(value, digits ?? 2);
    case "pct":
      return fmtPct(value, digits ?? 1, signed);
    case "pctpoints":
      return fmtPctPoints(value, digits ?? 2, signed);
    case "ratio":
      return fmtRatio(value, digits ?? 2);
    case "compact":
      return fmtCompact(value);
    case "compactkes":
      return fmtCompactKes(value);
    case "int":
      return fmtInt(value);
    case "score":
      return fmtNum(value, digits ?? 1);
    default:
      return fmtNum(value, digits ?? 2);
  }
}

/**
 * The one way a number is rendered. A known value is formatted; an explicit zero is
 * "0" with a title saying so; every other status is a labelled chip carrying the
 * reason - never "0", "-" or blank.
 */
export function Measure({ m, kind = "num", digits, signed = false, showReason = false, className = "" }: MeasureProps) {
  if (!m) {
    return (
      <span className={`measure measure--na ${className}`} title="not in the response" aria-label="missing: not in the response">
        missing
      </span>
    );
  }
  if (isKnown(m)) {
    const text = formatValue(m.value, kind, digits, signed);
    const tone = signed ? (m.value > 0 ? "pos" : m.value < 0 ? "neg" : "") : "";
    const title = m.status === "zero" ? "explicit zero from the source" : undefined;
    return (
      <span className={`measure ${tone} ${className}`} title={title}>
        {text}
      </span>
    );
  }
  const reason = m.reason ?? m.status;
  return (
    <span className={`measure ${className}`}>
      <span className="measure--na" title={reason} aria-label={`${m.status}: ${reason}`}>
        {statusLabel(m.status)}
      </span>
      {showReason && m.reason ? <span className="reason">{m.reason}</span> : null}
    </span>
  );
}
