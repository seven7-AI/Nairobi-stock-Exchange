import type { ReactNode } from "react";

export function KeyValueList({ items }: { items: { label: string; value: ReactNode; hint?: string }[] }) {
  return (
    <dl className="kv">
      {items.map((item) => (
        <div key={item.label} style={{ display: "contents" }}>
          <dt title={item.hint}>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
