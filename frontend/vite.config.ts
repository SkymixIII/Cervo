import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Frontend V1 = localhost only. On proxifie /api vers l'API FastAPI (uvicorn 8000).
// Le proxy http-proxy laisse passer le streaming SSE de /api/jobs/{id}/events tel quel.
const API_TARGET = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
});
