import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DataTable } from "../components/ui/DataTable";

const rows = [
  { t: "KCB", pe: 4.33 },
  { t: "SCOM", pe: null },
  { t: "EQTY", pe: 5.34 },
  { t: "BAT", pe: 8.9 },
];

function cells(): string[] {
  return within(screen.getByRole("table")).getAllByRole("row").slice(1).map((r) => r.querySelector("td")!.textContent!);
}

describe("DataTable", () => {
  it("sorts with unknown values last in both directions and searches", async () => {
    const user = userEvent.setup();
    render(
      <DataTable
        rows={rows}
        rowKey={(r) => r.t}
        searchable
        searchText={(r) => r.t}
        columns={[
          { key: "t", header: "Ticker", cell: (r) => r.t, sortValue: (r) => r.t },
          { key: "pe", header: "P/E", cell: (r) => String(r.pe), sortValue: (r) => r.pe },
        ]}
      />,
    );
    await user.click(screen.getByRole("button", { name: "P/E" }));
    expect(cells()).toEqual(["KCB", "EQTY", "BAT", "SCOM"]);
    expect(screen.getByRole("columnheader", { name: /P\/E/ })).toHaveAttribute("aria-sort", "ascending");
    await user.click(screen.getByRole("button", { name: "P/E" }));
    expect(cells()).toEqual(["BAT", "EQTY", "KCB", "SCOM"]);
    await user.type(screen.getByRole("searchbox"), "kc");
    expect(cells()).toEqual(["KCB"]);
  });
});
