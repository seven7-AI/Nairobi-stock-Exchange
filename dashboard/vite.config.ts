/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API the dev server proxies to: the standalone dashboard port.
const API_TARGET = process.env.VITE_API_TARGET ?? "http://127.0.0.1:4747";

export default defineConfig({
  plugins: [react()],
  base: "/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes("node_modules/recharts") || id.includes("node_modules/d3-")) return "recharts";
          if (id.includes("node_modules/react") || id.includes("node_modules/scheduler")) return "vendor";
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: { "/api": { target: API_TARGET, changeOrigin: false } },
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["src/test/setup.ts"],
    css: false,
    pool: "forks",
    maxWorkers: 2,
  },
});
