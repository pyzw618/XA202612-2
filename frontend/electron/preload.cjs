const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("memoryHubDesktop", {
  getRuntime: () => ipcRenderer.invoke("memoryhub:get-runtime"),
  checkBackend: () => ipcRenderer.invoke("memoryhub:check-backend"),
  openApiDocs: () => ipcRenderer.invoke("memoryhub:open-api-docs"),
});
