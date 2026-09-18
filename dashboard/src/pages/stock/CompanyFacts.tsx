import type { StockDetail } from "../../api/types";
import { Card } from "../../components/ui/Card";
import { KeyValueList } from "../../components/ui/KeyValueList";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { fmtCompactKes, fmtDate, fmtInt } from "../../lib/format";

export function CompanyFacts({ facts, geographic, quote }: { facts: StockDetail["facts"]; geographic: StockDetail["geographic"]; quote: StockDetail["quote"] }) {
  const countries = geographic.operating_countries ?? [];
  return (
    <Card title="Company" span={geographic.status === "known" ? 2 : undefined}>
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
          ...(facts.ceo ? [{ label: "CEO", value: facts.ceo }] : []),
          ...(facts.website ? [{ label: "Website", value: <a href={facts.website} rel="noreferrer noopener" target="_blank">{facts.website}</a> }] : []),
          ...(facts.address ? [{ label: "Address", value: facts.address }] : []),
          ...(facts.exchange ? [{ label: "Exchange", value: facts.exchange }] : []),
          ...(facts.fiscal_year ? [{ label: "Fiscal year", value: facts.fiscal_year }] : []),
          ...(facts.currency ? [{ label: "Reporting currency", value: facts.currency }] : []),
          ...(facts.sic ? [{ label: "SIC", value: facts.sic }] : []),
          {
            label: "Geographic exposure",
            value:
              geographic.status === "known" ? (
                <>
                  <span className="chips">
                    {countries.map((c) => (
                      <span key={c} className="chip">
                        {c === geographic.home_country ? `${c} (home)` : c}
                      </span>
                    ))}
                  </span>
                  <div className="muted small" style={{ marginTop: 4 }}>
                    {geographic.note}
                  </div>
                </>
              ) : (
                <>
                  <StatusBadge status={geographic.status} title={geographic.reason ?? undefined} /> <span className="muted small">{geographic.reason}</span>
                </>
              ),
          },
        ]}
      />
      {geographic.description ? (
        <details style={{ marginTop: 8 }}>
          <summary>Business description (stockanalysis.com)</summary>
          <p className="small" style={{ whiteSpace: "normal" }}>
            {geographic.description}
          </p>
        </details>
      ) : null}
      {facts.executives?.length ? (
        <details style={{ marginTop: 4 }}>
          <summary>Executives</summary>
          <ul className="small">
            {facts.executives.map((e) => (
              <li key={e.name}>
                {e.name}
                {e.title ? ` — ${e.title}` : ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </Card>
  );
}
