/**
 * AuricTerminal Electron shell.
 *
 * Strategy: keep one backend (FastAPI in server.py) as the source of truth.
 * This shell spawns `python ../run_server.py` (or the python selected via
 * AURIC_PYTHON) on 127.0.0.1:8000, waits for /api/health, then loads it.
 * The backend serves the built web UI (web/dist), so the window stays
 * same-origin — no CORS changes needed.
 *
 * Env overrides:
 *   AURIC_BACKEND_URL  — use an already-running backend instead of spawning
 *                        (e.g. http://127.0.0.1:8000)
 *   AURIC_PORT         — port for the spawned backend (default 8000)
 *   AURIC_PYTHON       — python executable (default "python")
 *   AURIC_NO_SPAWN     — set to "1" to never spawn a backend
 */
const { app, BrowserWindow, dialog, shell } = require('electron');
const path = require('node:path');
const { spawn } = require('node:child_process');

const PORT = Number(process.env.AURIC_PORT || 8000);
const BACKEND_URL = process.env.AURIC_BACKEND_URL || `http://127.0.0.1:${PORT}`;
const APP_ROOT = path.join(__dirname, '..'); // repo root (server.py lives here)

let backendProc = null;
let mainWindow = null;

function spawnBackend() {
  if (process.env.AURIC_NO_SPAWN === '1' || process.env.AURIC_BACKEND_URL) return;
  const python = process.env.AURIC_PYTHON || 'python';
  // run_server.py binds 127.0.0.1:8000 and loads .env from APP_ROOT.
  backendProc = spawn(python, ['run_server.py'], {
    cwd: APP_ROOT,
    env: { ...process.env, PORT: String(PORT) },
    stdio: 'ignore',
    windowsHide: true,
  });
  backendProc.on('error', (err) => {
    dialog.showErrorBox(
      'Backend failed to start',
      `Could not spawn "${python} run_server.py".\n${String(err)}\n\n` +
        'Install Python deps (pip install -r requirements.txt) or set AURIC_BACKEND_URL.'
    );
  });
}

async function waitForBackend(timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/health`);
      if (res.ok) return true;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    backgroundColor: '#0a0e14',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadURL(BACKEND_URL);
  // Open external links in the OS browser, not in the app window.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(BACKEND_URL)) {
      shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });
}

app.whenReady().then(async () => {
  spawnBackend();
  const ok = await waitForBackend();
  if (!ok) {
    dialog.showErrorBox(
      'Backend not reachable',
      `AuricTerminal backend did not respond at ${BACKEND_URL}.\n\n` +
        'Start it manually:  uvicorn server:app --host 127.0.0.1 --port 8000'
    );
  }
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  if (backendProc) {
    try {
      backendProc.kill();
    } catch {
      // already gone
    }
    backendProc = null;
  }
});
