import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/layout/Layout";
import { Loading } from "./components/ui/States";
import { NotFound } from "./pages/NotFound";
import { Placeholder } from "./pages/Placeholder";

const Overview = lazy(() => import("./pages/Overview").then((m) => ({ default: m.Overview })));
const System = lazy(() => import("./pages/System").then((m) => ({ default: m.System })));

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Suspense fallback={<Loading />}><Overview /></Suspense>} />
        <Route path="market" element={<Placeholder title="Market" />} />
        <Route path="stocks" element={<Placeholder title="Stocks" />} />
        <Route path="stocks/:ticker" element={<Placeholder title="Stock" />} />
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
