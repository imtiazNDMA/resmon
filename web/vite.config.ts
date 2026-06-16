import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server proxies /api to the FastAPI backend (or the Caddy proxy in compose).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:18000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ""),
      },
    },
  },
});
