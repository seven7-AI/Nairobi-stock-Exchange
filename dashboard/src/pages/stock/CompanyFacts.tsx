import type { StockDetail } from "../../api/types";
import { Card } from "../../components/ui/Card";
import { KeyValueList } from "../../components/ui/KeyValueList";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { fmtCompactKes, fmtDate, fmtInt } from "../../lib/format";

export function CompanyFacts({ facts, geographic, quote }: { facts: StockDetail["facts"]; geographic: StockDetail["geographic"]; quote: StockDetail["quote"] }) {
  return (
    <Card title="Company">
      <KeyValueList
        items={[
          { label: "Name", value: facts.company_name ?? quote.company_name ?? "—" },
          { label: "Sector", value: facts.sector ?? "—" },
          { label: "Industry", value: facts.industry ?? "—" },
          { label: "Founded", value: facts.founded ?? "—" },
          { label: "Employees", value: typeof facts.employees === "number" ? fmtInt(facts.employees) : "—" },
          { label: "Revenue (scraped)", value: typeof facts.revenue === "number" ? fmtCompactKes(facts.revenue) : "—" },
          { label: "Listed since", value: fmtDate(facts.listed_since) },
          { label: "Classified from", value: typeof facts.classification_source === "string" ? facts.classification_source : "—" },
          {
            label: "Geographic exposure",
            value: (
              <>
                <StatusBadge status={geographic.status} title={geographic.reason} /> <span className="muted small">{geographic.reason}</span>
              </>
            ),
          },
        ]}
      />
    </Card>
  );
}
