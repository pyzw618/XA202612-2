const { app, BrowserWindow, ipcMain, shell } = require("electron");
const path = require("node:path");
const { startUiServer } = require("./ui-server.cjs");

const backendUrl = (process.env.MEMORYHUB_BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
const developmentUrl = process.env.ELECTRON_RENDERER_URL || "http://127.0.0.1:3000";

let mainWindow = null;
let uiServer = null;
let uiOrigin = developmentUrl;

async function getBackendStatus() {
  const startedAt = Date.now();
  try {
    const response = await fetch(`${backendUrl}/api/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2500),
    });
    return {
      online: response.ok,
      backendUrl,
      latencyMs: Date.now() - startedAt,
      checkedAt: new Date().toISOString(),
    };
  } catch (error) {
    return {
      online: false,
      backendUrl,
      latencyMs: Date.now() - startedAt,
      checkedAt: new Date().toISOString(),
      message: error instanceof Error ? error.message : "MemoryHub service unavailable",
    };
  }
}

function registerDesktopIpc() {
  ipcMain.handle("memoryhub:get-runtime", async () => ({
    desktop: true,
    platform: process.platform,
    arch: process.arch,
    appVersion: app.getVersion(),
    backend: await getBackendStatus(),
  }));

  ipcMain.handle("memoryhub:check-backend", getBackendStatus);
  ipcMain.handle("memoryhub:open-api-docs", async () => {
    await shell.openExternal(`${backendUrl}/docs`);
    return true;
  });
}

async function createWindow() {
  if (app.isPackaged) {
    uiServer = await startUiServer({
      distDir: path.join(app.getAppPath(), "dist"),
      host: "127.0.0.1",
      port: 0,
    });
    uiOrigin = uiServer.url;
  }

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1100,
    minHeight: 720,
    show: false,
    backgroundColor: "#f4f7fb",
    title: "MemoryHub",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) void shell.openExternal(url);
    return { action: "deny" };
  });

  mainWindow.webContents.on("will-navigate", (event, targetUrl) => {
    if (new URL(targetUrl).origin !== new URL(uiOrigin).origin) {
      event.preventDefault();
      if (/^https?:\/\//i.test(targetUrl)) void shell.openExternal(targetUrl);
    }
  });

  mainWindow.once("ready-to-show", () => mainWindow?.show());
  await mainWindow.loadURL(uiOrigin);
}

const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });

  app.whenReady().then(async () => {
    registerDesktopIpc();
    await createWindow();

    app.on("activate", async () => {
      if (BrowserWindow.getAllWindows().length === 0) await createWindow();
    });
  });
}

app.on("window-all-closed", () => {
  // The MemoryHub backend is an independent service. Closing Electron only
  // closes the management client and never sends a stop signal to the backend.
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", async () => {
  if (uiServer) {
    await uiServer.close();
    uiServer = null;
  }
});
