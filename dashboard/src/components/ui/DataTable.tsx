import type { ReactNode } from "react";
import { useTableState, type SortValue } from "../../hooks/useTableState";

export interface Column<T> {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  sortValue?: (row: T) => SortValue;
  align?: "left" | "right";
  title?: string;
}

export function DataTable<T>({ rows, columns, rowKey, searchText, initialSort, initialDirection, emptyText = "nothing to show", searchable = false, dense = false }: {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  searchText?: (row: T) => string;
  initialSort?: string;
  initialDirection?: "asc" | "desc";
  emptyText?: string;
  searchable?: boolean;
  dense?: boolean;
}) {
  const byKey = new Map(columns.map((c) => [c.key, c]));
  const { rows: visible, state } = useTableState(rows, {
    sortValue: (row, key) => byKey.get(key)?.sortValue?.(row) ?? null,
    searchText,
    initialSort,
    initialDirection,
  });
  return (
    <div>
      {searchable ? (
        <div className="controls" style={{ marginBottom: 8 }}>
          <input type="search" placeholder="Search…" value={state.search} onChange={(e) => state.setSearch(e.target.value)} aria-label="Search rows" />
          <span className="muted small">
            {visible.length} of {rows.length}
          </span>
        </div>
      ) : null}
      <div className="table-wrap">
        <table className={dense ? "small" : ""}>
          <thead>
            <tr>
              {columns.map((c) => {
                const sortable = !!c.sortValue;
                const active = state.sortKey === c.key;
                return (
                  <th key={c.key} className={c.align === "right" ? "num" : ""} title={c.title} aria-sort={active ? (state.direction === "asc" ? "ascending" : "descending") : sortable ? "none" : undefined}>
                    {sortable ? (
                      <button type="button" onClick={() => state.toggleSort(c.key)}>
                        {c.header}
                      </button>
                    ) : (
                      c.header
                    )}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="muted">
                  {emptyText}
                </td>
              </tr>
            ) : (
              visible.map((row) => (
                <tr key={rowKey(row)}>
                  {columns.map((c) => (
                    <td key={c.key} className={c.align === "right" ? "num" : ""}>
                      {c.cell(row)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
