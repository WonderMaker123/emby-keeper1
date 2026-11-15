import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

// 本地开发默认输出到 Flask 静态目录, 便于直接刷新页面即可看到效果.
// Docker 构建时由环境变量指定 /fe/dist, 再由 Dockerfile 复制进运行镜像.
const outDir =
  process.env.VITE_OUT_DIR || fileURLToPath(new URL("../embykeeperweb/templates/assets/dist", import.meta.url));

export default defineConfig({
  plugins: [vue()],
  // 使用相对路径, 兼容任意部署前缀 (Flask 的 --prefix)
  base: "./",
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir,
    emptyOutDir: true,
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5173,
    // 开发期把 API 与 SocketIO 代理到 Flask, 避免跨域
    proxy: {
      "/api": { target: "http://127.0.0.1:1818", changeOrigin: true },
      "/socket.io": { target: "http://127.0.0.1:1818", ws: true, changeOrigin: true },
    },
  },
});
