import type { Measure } from "../api/types";

export function isKnown(m: Measure | null | undefined): m is Measure & { value: number } {
  return !!m && (m.status === "known" || m.status === "zero") && typeof m.value === "number";
}

export function valueOf(m: Measure | null | undefined): number | null {
  return isKnown(m) ? m.value : null;
}

export const STATUS_LABEL: Record<string, string> = {
  known: "known",
  zero: "0",
  missing: "missing",
  unavailable: "unavailable",
  not_applicable: "n/a",
  not_meaningful: "not meaningful",
  partial: "partial",
};

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}
