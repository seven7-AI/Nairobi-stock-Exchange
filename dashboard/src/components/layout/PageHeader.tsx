import { useEffect, type ReactNode } from "react";

export function PageHeader({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  useEffect(() => {
    document.title = `${title} · NSE Analytics`;
  }, [title]);
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {sub ? <div className="sub">{sub}</div> : null}
      </div>
      {children ? <div className="controls">{children}</div> : null}
    </div>
  );
}
