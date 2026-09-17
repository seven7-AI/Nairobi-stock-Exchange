import { PageHeader } from "../components/layout/PageHeader";

/** Pages that land in the next issues; nothing invented in the meantime. */
export function Placeholder({ title }: { title: string }) {
  return (
    <>
      <PageHeader title={title} />
      <p className="muted">This page arrives with the next dashboard issue.</p>
    </>
  );
}
