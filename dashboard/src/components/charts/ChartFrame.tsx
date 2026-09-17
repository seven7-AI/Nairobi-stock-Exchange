import type { ReactNode } from "react";

export function ChartFrame({ title, caption, height = 260, children }: { title?: string; caption?: ReactNode; height?: number; children: ReactNode }) {
  return (
    <figure style={{ margin: 0 }}>
      {title ? <h3 style={{ marginBottom: 6 }}>{title}</h3> : null}
      <div style={{ width: "100%", height, maxWidth: "100%" }}>{children}</div>
      {caption ? (
        <figcaption className="muted small" style={{ marginTop: 6 }}>
          {caption}
        </figcaption>
      ) : null}
    </figure>
  );
}
