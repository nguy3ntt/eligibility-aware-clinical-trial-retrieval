import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Same-origin browser calls; no public host, credentials or backend CORS relaxation.
const proxy = {
  "/v1": { target: "http://127.0.0.1:8000", changeOrigin: false },
};
export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy,
    fs: { strict: true },
  },
  preview: { host: "127.0.0.1", port: 5173, strictPort: true, proxy },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
  },
});
