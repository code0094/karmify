// Electron main process: launches the Python sidecar, then opens the window.
import { app, BrowserWindow } from "electron";
import { spawn } from "node:child_process";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");

const SIDECAR_HOST = process.env.AUX_SIDECAR_HOST || "127.0.0.1";
const SIDECAR_PORT = process.env.AUX_SIDECAR_PORT || "8765";
const SIDECAR_URL = `http://${SIDECAR_HOST}:${SIDECAR_PORT}`;

let sidecar = null;
let win = null;

function startSidecar() {
  // Reuse the project's Python; override with AUX_PYTHON (e.g. a venv path).
  const python = process.env.AUX_PYTHON || "python";
  sidecar = spawn(python, ["-m", "src.sidecar.app"], {
    cwd: PROJECT_ROOT,
    env: { ...process.env },
    stdio: "inherit",
  });
  sidecar.on("exit", (code) => {
    console.log(`[sidecar] exited with code ${code}`);
    sidecar = null;
  });
}

function waitForSidecar(retries = 60) {
  return new Promise((resolve, reject) => {
    const attempt = (n) => {
      const req = http.get(`${SIDECAR_URL}/health`, (res) => {
        res.resume();
        resolve();
      });
      req.on("error", () => {
        if (n <= 0) reject(new Error("sidecar did not become healthy"));
        else setTimeout(() => attempt(n - 1), 500);
      });
    };
    attempt(retries);
  });
}

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
