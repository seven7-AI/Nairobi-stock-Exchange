import { NavLink, Outlet } from "react-router-dom";
import { LiveIndicator } from "./LiveIndicator";

const PAGES: [string, string][] = [
  ["/", "Overview"],
  ["/market", "Market"],
  ["/stocks", "Stocks"],
  ["/analytics", "Analytics"],
  ["/forecasts", "Forecasts"],
  ["/signals", "Signals"],
  ["/backtests", "Backtests"],
  ["/system", "System"],
];

export function Layout() {
  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/" className="brand">
            NSE <span>Analytics</span>
          </NavLink>
          <nav className="nav" aria-label="Pages">
            {PAGES.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "active" : "")}>
                {label}
              </NavLink>
            ))}
          </nav>
          <LiveIndicator />
        </div>
      </header>
      <main className="page">
        <Outlet />
      </main>
      <footer className="foot">Nairobi Securities Exchange · stored model outputs, missing is never shown as zero · not investment advice</footer>
    </div>
  );
}
