import { useMemo, useState } from "react";

export type SortDirection = "asc" | "desc";
export type SortValue = number | string | null | undefined;

export interface TableState {
  sortKey: string | null;
  direction: SortDirection;
  search: string;
  setSearch: (value: string) => void;
  toggleSort: (key: string) => void;
}

/** Sort with nulls last whichever the direction; search across chosen fields. */
export function useTableState<T>(
  rows: T[],
  options: { sortValue: (row: T, key: string) => SortValue; searchText?: (row: T) => string; initialSort?: string; initialDirection?: SortDirection },
): { rows: T[]; state: TableState } {
  const [sortKey, setSortKey] = useState<string | null>(options.initialSort ?? null);
  const [direction, setDirection] = useState<SortDirection>(options.initialDirection ?? "asc");
  const [search, setSearch] = useState("");

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    let out = needle && options.searchText ? rows.filter((r) => options.searchText!(r).toLowerCase().includes(needle)) : [...rows];
    if (sortKey) {
      const known = out.filter((r) => isPresent(options.sortValue(r, sortKey)));
      const unknown = out.filter((r) => !isPresent(options.sortValue(r, sortKey)));
      known.sort((a, b) => compare(options.sortValue(a, sortKey), options.sortValue(b, sortKey)) * (direction === "asc" ? 1 : -1));
      out = [...known, ...unknown];
    }
    return out;
  }, [rows, search, sortKey, direction, options]);

  const toggleSort = (key: string) => {
    if (key === sortKey) setDirection((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(key);
      setDirection("asc");
    }
  };

  return { rows: visible, state: { sortKey, direction, search, setSearch, toggleSort } };
}

function isPresent(v: SortValue): boolean {
  return v !== null && v !== undefined && !(typeof v === "number" && Number.isNaN(v));
}

function compare(a: SortValue, b: SortValue): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b));
}
