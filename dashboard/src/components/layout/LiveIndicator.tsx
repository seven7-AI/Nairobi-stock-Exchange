import { useVersion } from "../../hooks/useVersion";
import { fmtAgo, fmtDate } from "../../lib/format";

export function LiveIndicator() {
  const { snapshot, pollError, refreshing, lastPolledAt, refreshNow } = useVersion();
  const title = pollError
    ? `poll failed: ${pollError}`
    : `store version ${snapshot?.version ?? "?"} · polled ${fmtAgo(lastPolledAt?.toISOString())}`;
  return (
    <div className="live" title={title}>
      <span className={`dot ${refreshing ? "is-refreshing" : ""} ${pollError ? "is-error" : ""}`} aria-hidden="true" />
      {pollError ? (
        <span className="neg">API unreachable</span>
      ) : (
        <>
          <span>
            data <b>{fmtDate(snapshot?.latest_market_date)}</b>
          </span>
          <span className="muted">·</span>
          <span>
            analytics <b>{fmtAgo(snapshot?.analytics_updated_at)}</b>
          </span>
          <span className="muted">·</span>
          <span>
            scrape <b>{fmtAgo(snapshot?.scraper_updated_at)}</b>
          </span>
        </>
      )}
      <button type="button" onClick={refreshNow} className="small" aria-label="Refresh now" title="Refresh now">
        ↻
      </button>
    </div>
  );
}
