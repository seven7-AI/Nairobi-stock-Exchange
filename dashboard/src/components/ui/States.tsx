export function Loading({ rows = 4 }: { rows?: number }) {
  return (
    <div className="state" role="status" aria-live="polite">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" style={{ width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function ErrorState({ error, status, onRetry }: { error: string; status?: number; onRetry?: () => void }) {
  return (
    <div className="state error" role="alert">
      <p>
        {status ? `${status} — ` : ""}
        {error}
      </p>
      {onRetry ? <button onClick={onRetry}>Retry</button> : null}
    </div>
  );
}

export function EmptyState({ text }: { text: string }) {
  return <div className="state">{text}</div>;
}
