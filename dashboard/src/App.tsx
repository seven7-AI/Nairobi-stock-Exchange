import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/layout/Layout";
import { Loading } from "./components/ui/States";
import { NotFound } from "./pages/NotFound";
import { Placeholder } from "./pages/Placeholder";

const Overview = lazy(() => import("./pages/Overview").then((m) => ({ default: m.Overview })));
const System = lazy(() => import("./pages/System").then((m) => ({ default: m.System })));
const Market = lazy(() => import("./pages/Market").then((m) => ({ default: m.Market })));
const Stocks = lazy(() => import("./pages/Stocks").then((m) => ({ default: m.Stocks })));
const StockDetail = lazy(() => import("./pages/StockDetail").then((m) => ({ default: m.StockDetail })));

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Suspense fallback={<Loading />}><Overview /></Suspense>} />
        <Route path="market" element={<Suspense fallback={<Loading />}><Market /></Suspense>} />
        <Route path="stocks" element={<Suspense fallback={<Loading />}><Stocks /></Suspense>} />
        <Route path="stocks/:ticker" element={<Suspense fallback={<Loading />}><StockDetail /></Suspense>} />
        <Route path="analytics" element={<Placeholder title="Analytics" />} />
        <Route path="forecasts" element={<Placeholder title="Forecasts" />} />
        <Route path="signals" element={<Placeholder title="Signals" />} />
        <Route path="backtests" element={<Placeholder title="Backtests" />} />
        <Route path="system" element={<Suspense fallback={<Loading />}><System /></Suspense>} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
