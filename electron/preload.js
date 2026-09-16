const { contextBridge } = require('electron');

// Minimal, safe bridge. The UI talks to the backend over HTTP/WS
// (same origin), so no privileged APIs are exposed here.
contextBridge.exposeInMainWorld('auricDesktop', {
  platform: process.platform,
  version: '0.2.0',
});
