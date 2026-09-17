import type { ReactNode } from "react";
import type { Measure as MeasureT } from "../../api/types";
import { isKnown } from "../../lib/measure";
import { Measure, type MeasureKind } from "../ui/Measure";

/** Horizontal bars for a short list; non-known items show their status chip. */
export function BarList({ items, kind = "pct", signed = true }: { items: { label: ReactNode; key: string; value: MeasureT; hint?: string }[]; kind?: MeasureKind; signed?: boolean }) {
  const known = items.filter((i) => isKnown(i.value)).map((i) => Math.abs(i.value.value as number));
  const max = Math.max(...known, 1e-9);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(90px, max-content) 1fr max-content", gap: "4px 10px", alignItems: "center" }}>
      {items.map((i) => {
        const v = isKnown(i.value) ? (i.value.value as number) : null;
        const width = v === null ? 0 : (Math.abs(v) / max) * 100;
        const tone = !signed ? "var(--accent)" : v !== null && v < 0 ? "var(--neg)" : "var(--pos)";
        return (
          <div key={i.key} style={{ display: "contents" }}>
            <div title={i.hint} className="nowrap">
              {i.label}
            </div>
            <div style={{ height: 8, background: "var(--surface-2)", borderRadius: 4, overflow: "hidden" }} aria-hidden="true">
              <div style={{ width: `${width}%`, height: "100%", background: tone, borderRadius: 4 }} />
            </div>
            <div className="num">
              <Measure m={i.value} kind={kind} signed={signed} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
