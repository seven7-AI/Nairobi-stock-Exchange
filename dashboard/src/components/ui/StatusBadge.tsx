export type Tone = "ok" | "warn" | "error" | "muted" | "info";

const TONES: Record<string, Tone> = {
  succeeded: "ok",
  ok: "ok",
  active: "ok",
  known: "ok",
  "buy candidate": "ok",
  stale: "warn",
  warning: "warn",
  candidate: "warn",
  running: "warn",
  watch: "info",
  neutral: "muted",
  weak: "warn",
  avoid: "error",
  failed: "error",
  error: "error",
  unreachable: "error",
  rejected: "error",
  degraded: "warn",
  skipped: "muted",
  unavailable: "muted",
  missing: "muted",
  disabled: "muted",
  retired: "muted",
  partial: "warn",
  info: "info",
};

export function toneFor(status: string | null | undefined): Tone {
  return TONES[(status ?? "").toLowerCase()] ?? "muted";
}

export function StatusBadge({ status, tone, title }: { status: string | null | undefined; tone?: Tone; title?: string }) {
  const text = status ?? "unknown";
  return (
    <span className={`badge badge--${tone ?? toneFor(text)}`} title={title} aria-label={title ? `${text}: ${title}` : text}>
      {text}
    </span>
  );
}
