// Capture real API payloads into src/test/fixtures/ (never hand-written test data).
//   VITE_API_TARGET=http://127.0.0.1:4747 node scripts/capture-fixtures.mjs
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const target = process.env.VITE_API_TARGET ?? "http://127.0.0.1:4747";
const base = `${target}/api/v1/dashboard`;
const out = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "test", "fixtures");
const captures = {
  "version.json": "/status/version",
  "status.json": "/status",
  "overview.json": "/overview",
  "market.json": "/market",
  "stocks.json": "/stocks?limit=200",
  "stock-KCB.json": "/stocks/KCB",
  "prices-KCB-max.json": "/stocks/KCB/prices?range=max&interval=weekly",
  "analytics.json": "/analytics",
  "forecasts-KCB.json": "/forecasts?ticker=KCB",
  "signals.json": "/signals",
  "backtests.json": "/backtests",
  "backtest-1.json": "/backtests/1",
};

await mkdir(out, { recursive: true });
const manifest = {};
for (const [file, path] of Object.entries(captures)) {
  const response = await fetch(`${base}${path}`);
  if (!response.ok) {
    console.error(`${path}: ${response.status}`);
    continue;
  }
  const text = await response.text();
  await writeFile(join(out, file), text);
  manifest[file] = { path, captured_at: new Date().toISOString(), bytes: text.length, store_version: response.headers.get("x-store-version") };
  console.log(`${file}: ${text.length} bytes`);
}
await writeFile(join(out, "manifest.json"), JSON.stringify(manifest, null, 2));
