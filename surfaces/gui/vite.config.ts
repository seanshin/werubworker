import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// `base: "./"` makes built asset URLs relative, so the bundle loads from the `tauri://`
// origin in the desktop shell (absolute `/assets` 404s there); a server-hosted build is
// unaffected. Dev runs on a fixed port (1420) with strictPort so the Tauri webview always
// loads the vite instance Tauri itself spawns (a drifting port would make the window load a
// stale/other server). `tauri.conf.json` devUrl must match this.

const stateDir = (): string =>
  process.env.WERUBWORKER_STATE_DIR ||
  process.env.COWORKER_STATE_DIR ||
  (process.platform === "win32"
    ? path.join(process.env.APPDATA || os.homedir(), "werubworker")
    : path.join(os.homedir(), ".config", "werubworker"));

const tokenPath = (): string => path.join(stateDir(), "sidecar-8765.token");

/** Read the sidecar token fresh from disk (survives server restarts). */
function readToken(): string {
  try {
    return fs.readFileSync(tokenPath(), "utf8").trim();
  } catch {
    return "";
  }
}

export default defineConfig(({ command }) => {
  // Token read at startup — used for the `define` injection into client JS.
  // The proxy uses a dynamic read (see `configure` below) so it always has
  // the latest token even after a server restart.
  const devToken = command === "serve" ? readToken() : "";

  return {
    base: "./",
    plugins: [react()],
    server: {
      port: 1420,
      strictPort: true,
      proxy: {
        "/v1": {
          target: "http://127.0.0.1:8765",
          changeOrigin: true,
          // Dynamic token: re-read from disk on every request so the proxy
          // survives backend restarts that regenerate the sidecar token.
          configure: (proxy) => {
            proxy.on("proxyReq", (proxyReq) => {
              const token = readToken();
              if (token) proxyReq.setHeader("X-WeruBWorker-Token", token);
            });
          },
        },
        "/ws": {
          target: "ws://127.0.0.1:8765",
          ws: true,
        },
      },
    },
    define: { __COWORKER_DEV_TOKEN__: JSON.stringify(devToken) },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            "vendor-react": ["react", "react-dom"],
            "vendor-xlsx": ["xlsx"],
            "vendor-markdown": ["react-markdown", "remark-gfm"],
            "vendor-i18n": ["i18next", "react-i18next"],
          },
        },
      },
    },
    // Tauri CLI looks for these; harmless for the browser build.
    clearScreen: false,
    envPrefix: ["VITE_", "TAURI_"],
  };
});
