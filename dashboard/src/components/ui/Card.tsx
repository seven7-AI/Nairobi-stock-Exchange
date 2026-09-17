import type { ReactNode } from "react";
import { fmtDate } from "../../lib/format";

export function Card({ title, subtitle, actions, asOf, span, children, className = "" }: { title?: string; subtitle?: string; actions?: ReactNode; asOf?: string | null; span?: 2 | 3; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${span ? `span-${span}` : ""} ${className}`}>
      {title || actions ? (
        <div className="card-head">
          <div>
            {title ? <h2>{title}</h2> : null}
            {subtitle ? <div className="meta">{subtitle}</div> : null}
          </div>
          <div className="controls">
            {asOf ? <span className="meta">as of {fmtDate(asOf)}</span> : null}
            {actions}
          </div>
        </div>
      ) : null}
      {children}
    </section>
  );
}
