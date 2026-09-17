import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Measure } from "../components/ui/Measure";

describe("Measure renders missing ≠ zero", () => {
  it("formats a known value by kind", () => {
    render(<Measure m={{ value: 0.0542, status: "known", reason: null }} kind="pct" />);
    expect(screen.getByText("5.4 %")).toBeInTheDocument();
  });
  it("shows an explicit zero as 0 with a title", () => {
    render(<Measure m={{ value: 0, status: "zero", reason: null }} kind="pct" />);
    const el = screen.getByText("0.0 %");
    expect(el).toHaveAttribute("title", "explicit zero from the source");
  });
  it.each(["missing", "unavailable", "not_applicable", "not_meaningful"])("renders %s as a labelled chip, never 0", (status) => {
    const reason = `${status}: because of the 572-day gap`;
    render(<Measure m={{ value: null, status, reason }} kind="pct" />);
    const chip = screen.getByTitle(reason);
    expect(chip).toHaveAttribute("aria-label", `${status}: ${reason}`);
    expect(chip.textContent).not.toMatch(/^0|^-$|^$/);
  });
  it("labels not_applicable as n/a", () => {
    render(<Measure m={{ value: null, status: "not_applicable", reason: "bank" }} />);
    expect(screen.getByText("n/a")).toBeInTheDocument();
  });
  it("can show the reason inline", () => {
    render(<Measure m={{ value: null, status: "unavailable", reason: "window crosses the gap" }} showReason />);
    expect(screen.getByText("window crosses the gap")).toBeInTheDocument();
  });
  it("treats an absent object as missing", () => {
    render(<Measure m={undefined} />);
    expect(screen.getByText("missing")).toHaveAttribute("title", "not in the response");
  });
  it("colours signed values by sign", () => {
    const { container } = render(<Measure m={{ value: -0.0244, status: "known", reason: null }} kind="pct" signed />);
    expect(container.querySelector(".neg")?.textContent).toBe("-2.4 %");
  });
});
