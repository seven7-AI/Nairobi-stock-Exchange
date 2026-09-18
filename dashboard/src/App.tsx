import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/layout/Layout";
import { Loading } from "./components/ui/States";
import { NotFound } from "./pages/NotFound";

const Overview = lazy(() => import("./pages/Overview").then((m) => ({ default: m.Overview })));
const System = lazy(() => import("./pages/System").then((m) => ({ default: m.System })));
const Market = lazy(() => import("./pages/Market").then((m) => ({ default: m.Market })));
const Stocks = lazy(() => import("./pages/Stocks").then((m) => ({ default: m.Stocks })));
const StockDetail = lazy(() => import("./pages/StockDetail").then((m) => ({ default: m.StockDetail })));
const Analytics = lazy(() => import("./pages/Analytics").then((m) => ({ default: m.Analytics })));
const Forecasts = lazy(() => import("./pages/Forecasts").then((m) => ({ default: m.Forecasts })));
const Signals = lazy(() => import("./pages/Signals").then((m) => ({ default: m.Signals })));
const Backtests = lazy(() => import("./pages/Backtests").then((m) => ({ default: m.Backtests })));

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Suspense fallback={<Loading />}><Overview /></Suspense>} />
        <Route path="market" element={<Suspense fallback={<Loading />}><Market /></Suspense>} />
        <Route path="stocks" element={<Suspense fallback={<Loading />}><Stocks /></Suspense>} />
        <Route path="stocks/:ticker" element={<Suspense fallback={<Loading />}><StockDetail /></Suspense>} />
        <Route path="analytics" element={<Suspense fallback={<Loading />}><Analytics /></Suspense>} />
        <Route path="forecasts" element={<Suspense fallback={<Loading />}><Forecasts /></Suspense>} />
        <Route path="signals" element={<Suspense fallback={<Loading />}><Signals /></Suspense>} />
        <Route path="backtests" element={<Suspense fallback={<Loading />}><Backtests /></Suspense>} />
        <Route path="system" element={<Suspense fallback={<Loading />}><System /></Suspense>} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
