export function Disclaimer({ text }: { text?: string | null }) {
  return <p className="disclaimer">{text ?? "Model outputs from stored, versioned calculations; not investment advice."}</p>;
}
