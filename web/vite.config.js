import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In compose, VITE_API_TARGET is http://api:8080. Running `npm run dev` on your
// own machine falls back to localhost. Later, Firebase Hosting rewrites /api to Cloud Run.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://localhost:8080",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
