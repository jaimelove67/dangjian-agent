import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig(({ mode }) => ({
  root: frontendRoot,
  envDir: frontendRoot,
  build: {
    outDir: "dist",
    rollupOptions: {
      output: {
        manualChunks: {
          charts: ["recharts"],
          icons: [
            "@phosphor-icons/react",
            "@iconify/react",
            "@iconify-icons/mdi/hammer-sickle",
          ],
        },
      },
    },
  },
  optimizeDeps: {
    include: ["react", "react-dom/client"],
  },
  server: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    watch: { ignored: ["**/tmp/**", "**/docs/screenshots/**"] },
    allowedHosts: ["terminal.local"],
    fs: {
      allow: [frontendRoot, fileURLToPath(new URL("../node_modules", import.meta.url))],
    },
    proxy: {
      "/api": {
        target:
          loadEnv(mode, frontendRoot, "").VITE_API_TARGET ||
          "http://127.0.0.1:8000",
        changeOrigin: true,
        configure(proxy) {
          // A proxy connection failure is different from a backend HTTP error.
          proxy.on("error", (_error, _request, response) => {
            if (
              !response ||
              typeof response.writeHead !== "function" ||
              response.headersSent ||
              response.writableEnded
            )
              return;
            response
              .writeHead(503, {
                "Content-Type": "application/json; charset=utf-8",
              })
              .end(
                JSON.stringify({
                  code: 503,
                  message:
                    "系统服务暂时无法连接，请稍后重试；如持续失败，请联系管理员。",
                }),
              );
          });
        },
      },
    },
    warmup: {
      clientFiles: ["./src/main.jsx"],
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    proxy: {
      "/api": {
        target: loadEnv(mode, frontendRoot, "").VITE_API_TARGET || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  plugins: [react()],
}));
