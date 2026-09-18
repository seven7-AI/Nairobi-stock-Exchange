import { fmtKes } from "../../lib/format";

/** bear · base · bull against the price. Renders nothing partial: any missing leg → a chip. */
export function RangeBar({ bear, base, bull, price, low, high }: { bear: number | null | undefined; base: number | null | undefined; bull: number | null | undefined; price: number | null | undefined; low?: number | null; high?: number | null }) {
  if (bear == null || base == null || bull == null) {
    return <span className="measure--na" title="one of bear / base / bull is not available">range unavailable</span>;
  }
  const values = [bear, base, bull, price ?? base, low ?? bear, high ?? bull];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pct = (v: number) => ((v - min) / span) * 100;
  return (
    <div>
      <div className="range-bar" role="img" aria-label={`bear ${fmtKes(bear)}, base ${fmtKes(base)}, bull ${fmtKes(bull)}${price != null ? `, price ${fmtKes(price)}` : ""}`}>
        <div className="track" />
        <div className="band" style={{ left: `${pct(bear)}%`, width: `${pct(bull) - pct(bear)}%` }} />
        <div className="tick" style={{ left: `${pct(base)}%` }} title={`base ${fmtKes(base)}`} />
        {price != null ? <div className="price" style={{ left: `${pct(price)}%` }} title={`price ${fmtKes(price)}`} /> : null}
      </div>
      <div className="range-labels">
        <span>bear {fmtKes(bear)}</span>
        <span>base {fmtKes(base)}</span>
        <span>bull {fmtKes(bull)}</span>
      </div>
    </div>
  );
}
