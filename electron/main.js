// Electron main process: launches the Python sidecar, then opens the window.
import { app, BrowserWindow, ipcMain } from "electron";
import { randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import http from "node:http";
import https from "node:https";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");

const SIDECAR_HOST = process.env.AUX_SIDECAR_HOST || "127.0.0.1";
const SIDECAR_PORT = process.env.AUX_SIDECAR_PORT || "8765";
const SIDECAR_URL = `http://${SIDECAR_HOST}:${SIDECAR_PORT}`;
// Per-run shared secret: the renderer's file:// origin is indistinguishable
// from any sandboxed iframe's, so the sidecar authenticates by token instead.
const SIDECAR_TOKEN = process.env.AUX_SIDECAR_TOKEN || randomBytes(32).toString("hex");
process.env.AUX_SIDECAR_TOKEN = SIDECAR_TOKEN;

let sidecar = null;
let win = null;

function startSidecar() {
  // The sidecar can live elsewhere (a server reached over an SSH tunnel), in
  // which case spawning a local one would just fight over the port.
  if (process.env.AUX_SIDECAR_EXTERNAL === "1") {
    console.log(`[sidecar] using external instance at ${SIDECAR_URL}`);
    return;
  }
  // Reuse the project's Python; override with AUX_PYTHON (e.g. a venv path).
  const python = process.env.AUX_PYTHON || "python";
  sidecar = spawn(python, ["-m", "src.sidecar.app"], {
    cwd: PROJECT_ROOT,
    env: {
      ...process.env,
      SIDECAR_AUTH_TOKEN: SIDECAR_TOKEN,
      // pydantic reads SIDECAR_HOST/PORT (no AUX_ prefix): forward the values
      // Electron connects to, or an AUX_SIDECAR_PORT override binds nothing.
      SIDECAR_HOST: SIDECAR_HOST,
      SIDECAR_PORT: SIDECAR_PORT,
    },
    stdio: "inherit",
  });
  sidecar.on("error", (err) => {
    // ENOENT (no python on PATH) would otherwise crash the main process
    // as an unhandled 'error' event before the window even opens.
    console.error(`[sidecar] failed to start: ${err.message}`);
    sidecar = null;
  });
  sidecar.on("exit", (code) => {
    console.log(`[sidecar] exited with code ${code}`);
    sidecar = null;
  });
}

function waitForUrl(url, what, retries = 60) {
  return new Promise((resolve, reject) => {
    const attempt = (n) => {
      const req = http.get(url, (res) => {
        res.resume();
        resolve();
      });
      req.on("error", () => {
        if (n <= 0) reject(new Error(`${what} did not become reachable`));
        else setTimeout(() => attempt(n - 1), 500);
      });
    };
    attempt(retries);
  });
}

const waitForSidecar = (retries = 60) =>
  waitForUrl(`${SIDECAR_URL}/health`, "sidecar", retries);

function fetchJson(url) {
  return new Promise((resolve, reject) => {
    https
      .get(url, { headers: { "User-Agent": "Karmify/0.1" } }, (res) => {
        let data = "";
        res.on("data", (chunk) => (data += chunk));
        res.on("end", () => {
          if (res.statusCode !== 200) return reject(new Error(`HTTP ${res.statusCode}`));
          try {
            resolve(JSON.parse(data));
          } catch (err) {
            reject(err);
          }
        });
      })
      .on("error", reject);
  });
}

// 30-second previews for the inbox come from the iTunes Search API: keyless
// and Spotify-independent. Fetched here in the main process — the renderer
// can't rely on CORS headers from apple.com.
ipcMain.handle("preview:search", async (_event, term) => {
  const query = encodeURIComponent(String(term));
  const url = `https://itunes.apple.com/search?term=${query}&media=music&entity=song&limit=3`;
  const data = await fetchJson(url);
  const hit = (data.results || []).find((r) => r.previewUrl);
  return hit ? { previewUrl: hit.previewUrl, matched: `${hit.artistName} — ${hit.trackName}` } : null;
});

async function createWindow() {
  win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  const devUrl = process.env.ELECTRON_RENDERER_URL;
  if (devUrl) {
    // `npm run dev` starts Vite and Electron together; without this the window
    // races the dev server and loads a blank page.
    await waitForUrl(devUrl, "vite dev server").catch((err) =>
      console.error(`[main] ${err.message}`),
    );
    await win.loadURL(devUrl);
  } else {
    await win.loadFile(path.join(__dirname, "dist", "index.html"));
  }
}

app.whenReady().then(async () => {
  startSidecar();
  try {
    await waitForSidecar();
  } catch (err) {
    console.error(`[main] ${err.message}`);
  }
  await createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("quit", () => {
  if (sidecar) sidecar.kill();
});
