import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const djangoTarget = process.env.VITE_DJANGO_URL || "http://127.0.0.1:8000";

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/static/react/" : "/",
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: djangoTarget,
        changeOrigin: true,
      },
      "/media": {
        target: djangoTarget,
        changeOrigin: true,
      },
    },
  },
}));
