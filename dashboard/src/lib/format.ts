// Formatting helpers. Ratios stored as fractions (0.0542) are shown as percentages.
const KES = new Intl.NumberFormat("en-KE", { style: "currency", currency: "KES", maximumFractionDigits: 2 });
const NUM = (digits: number) => new Intl.NumberFormat("en-KE", { maximumFractionDigits: digits, minimumFractionDigits: digits });
const INT = new Intl.NumberFormat("en-KE", { maximumFractionDigits: 0 });

export function fmtKes(v: number, digits = 2): string {
  if (digits === 2) return KES.format(v);
  return `KES ${NUM(digits).format(v)}`;
}

export function fmtCompactKes(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e12) return `KES ${NUM(2).format(v / 1e12)} tn`;
  if (abs >= 1e9) return `KES ${NUM(1).format(v / 1e9)} bn`;
  if (abs >= 1e6) return `KES ${NUM(1).format(v / 1e6)} m`;
  if (abs >= 1e3) return `KES ${NUM(1).format(v / 1e3)} k`;
  return KES.format(v);
}

export function fmtCompact(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${NUM(2).format(v / 1e9)} bn`;
  if (abs >= 1e6) return `${NUM(2).format(v / 1e6)} m`;
  if (abs >= 1e3) return `${NUM(1).format(v / 1e3)} k`;
  return INT.format(v);
}

export function fmtPct(v: number, digits = 1, signed = false): string {
  const text = `${NUM(digits).format(v * 100)} %`;
  return signed && v > 0 ? `+${text}` : text;
}

/** A percentage the source already expressed in percent points (e.g. 5.34). */
export function fmtPctPoints(v: number, digits = 2, signed = false): string {
  const text = `${NUM(digits).format(v)} %`;
  return signed && v > 0 ? `+${text}` : text;
}

export function fmtNum(v: number, digits = 2): string {
  return NUM(digits).format(v);
}

export function fmtInt(v: number): string {
  return INT.format(v);
}

export function fmtRatio(v: number, digits = 2): string {
  return `${NUM(digits).format(v)}×`;
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: iso.length === 10 ? "UTC" : undefined });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function fmtAgo(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "never";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return iso;
  const seconds = Math.max(0, Math.round((now.getTime() - then.getTime()) / 1000));
  if (seconds < 60) return `${seconds} s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} d ago`;
}

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
