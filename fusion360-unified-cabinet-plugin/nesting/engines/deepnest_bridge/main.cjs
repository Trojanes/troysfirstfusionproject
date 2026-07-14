/*
 * CabinetNC headless bridge for Deepnest-next v1.5.6.
 *
 * CabinetNC code talks JSON only. This file is the replaceable runtime adapter
 * around Deepnest's Electron renderer/IPC architecture.
 */
"use strict";

const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const net = require("node:net");
const { app, BrowserWindow, ipcMain } = require("electron");

const bridgeDir = __dirname;
const nestingDir = path.resolve(bridgeDir, "..", "..");
const vendorDir = path.join(nestingDir, "vendor", "deepnest-next");

// Prefer a private writable cache root so Electron GPU/disk caches do not
// collide with Fusion or fail with Access denied (0x5).
try {
  const userData = path.join(
    os.tmpdir(),
    `cabinetnc-deepnest-userdata-${process.pid}`,
  );
  fs.mkdirSync(userData, { recursive: true });
  app.setPath("userData", userData);
  app.commandLine.appendSwitch("disk-cache-size", "1");
} catch (_error) {
  // Continue with Electron defaults if tmp setup fails.
}

let runnerWindow = null;
let backgroundWindow = null;
let runnerReady = false;
let backgroundReady = false;
let shuttingDown = false;
let activeRequest = null;
let activeGeometrySignature = null;
let requestChain = Promise.resolve();
let server = null;
const backgroundRequestIds = [];
const portFileArgument = process.argv.indexOf("--port-file");
const portFile =
  portFileArgument >= 0 && process.argv[portFileArgument + 1]
    ? path.resolve(process.argv[portFileArgument + 1])
    : null;

console.log = (...values) => process.stderr.write(`${values.join(" ")}\n`);
console.warn = (...values) => process.stderr.write(`${values.join(" ")}\n`);
console.error = (...values) => process.stderr.write(`${values.join(" ")}\n`);

function writeResult(socket, payload) {
  return new Promise((resolve) => {
    if (socket.destroyed) {
      resolve();
      return;
    }
    socket.end(`${JSON.stringify(payload)}\n`, resolve);
  });
}

function errorMessage(error) {
  return error && error.stack ? error.stack : String(error);
}

function failActive(error) {
  if (!activeRequest) return;
  const request = activeRequest;
  activeRequest = null;
  backgroundRequestIds.length = 0;
  request.reject(error);
}

function windowsReady() {
  return runnerReady && backgroundReady;
}

function waitForWindows() {
  if (windowsReady()) return Promise.resolve();
  return new Promise((resolve, reject) => {
    let poll = null;
    const deadline = setTimeout(
      () => {
        if (poll !== null) clearInterval(poll);
        reject(new Error("Deepnest windows did not become ready."));
      },
      30000,
    );
    poll = setInterval(() => {
      if (windowsReady()) {
        clearInterval(poll);
        clearTimeout(deadline);
        resolve();
      }
    }, 20);
  });
}

async function clearGeometryCache() {
  await backgroundWindow.webContents.executeJavaScript(`
    (() => {
      if (!window.db || typeof window.db.getCache !== "function") {
        throw new Error("Deepnest NFP cache is unavailable.");
      }
      const cache = window.db.getCache();
      for (const key of Object.keys(cache)) delete cache[key];
      return Object.keys(cache).length;
    })()
  `);
}

async function runJob(request) {
  await waitForWindows();
  const signature = String(request.job?.geometrySignature || "");
  if (signature !== activeGeometrySignature) {
    await clearGeometryCache();
    activeGeometrySignature = signature;
  }
  return new Promise((resolve, reject) => {
    activeRequest = { id: request.id, resolve, reject };
    runnerWindow.webContents.send("cabinetnc-run-job", {
      ...request.job,
      requestId: request.id,
    });
  });
}

async function handleRequest(request, socket) {
  if (!request || typeof request !== "object" || request.id == null) {
    await writeResult(socket, {
      id: request?.id ?? null,
      ok: false,
      error: "Request needs an id.",
    });
    return;
  }
  if (request.op === "ping") {
    await writeResult(socket, { id: request.id, ok: true, pid: process.pid });
    return;
  }
  if (request.op === "shutdown") {
    await writeResult(socket, { id: request.id, ok: true, pid: process.pid });
    shuttingDown = true;
    if (server) {
      server.close(() => app.quit());
    } else {
      app.quit();
    }
    return;
  }
  if (request.op !== "run" || !request.job) {
    await writeResult(socket, {
      id: request.id,
      ok: false,
      error: "Unsupported bridge request.",
    });
    return;
  }
  try {
    const result = await runJob(request);
    await writeResult(socket, {
      id: request.id,
      ok: true,
      result,
      pid: process.pid,
    });
  } catch (error) {
    if (activeRequest?.id === request.id) activeRequest = null;
    await writeResult(socket, {
      id: request.id,
      ok: false,
      error: errorMessage(error),
      pid: process.pid,
    });
  }
}

function enqueueLine(line, socket) {
  let request;
  try {
    request = JSON.parse(line);
  } catch (error) {
    void writeResult(socket, {
      id: null,
      ok: false,
      error: `Invalid JSON: ${error}`,
    });
    return;
  }
  requestChain = requestChain
    .then(() => handleRequest(request, socket))
    .catch((error) => {
      return writeResult(socket, {
        id: request.id ?? null,
        ok: false,
        error: errorMessage(error),
      });
    });
}

function acceptConnection(socket) {
  socket.setEncoding("utf8");
  let input = "";
  let accepted = false;
  socket.on("data", (chunk) => {
    if (accepted) return;
    input += chunk;
    const newline = input.indexOf("\n");
    if (newline < 0) return;
    accepted = true;
    const line = input.slice(0, newline).trim();
    if (!line) {
      void writeResult(socket, {
        id: null,
        ok: false,
        error: "Request line must not be blank.",
      });
      return;
    }
    enqueueLine(line, socket);
  });
  socket.on("error", (error) => {
    process.stderr.write(`Bridge socket error: ${errorMessage(error)}\n`);
  });
}

async function writePortFile(port) {
  const temporary = `${portFile}.${process.pid}.${Date.now()}.tmp`;
  await fs.promises.writeFile(
    temporary,
    JSON.stringify({ port, pid: process.pid }),
    { encoding: "utf8", flag: "wx" },
  );
  await fs.promises.rename(temporary, portFile);
}

function listenOnLoopback() {
  return new Promise((resolve, reject) => {
    server = net.createServer(acceptConnection);
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.removeListener("error", reject);
      server.on("error", fatal);
      resolve(server.address().port);
    });
  });
}

function fatal(error) {
  const message = error && error.stack ? error.stack : String(error);
  process.stderr.write(`${message}\n`);
  failActive(error);
  if (!shuttingDown) {
    shuttingDown = true;
    app.quit();
  }
}

ipcMain.on("cabinetnc-runner-ready", (event) => {
  if (runnerWindow && event.sender === runnerWindow.webContents) {
    runnerReady = true;
  }
});

ipcMain.on("cabinetnc-result", (event, payload) => {
  if (
    runnerWindow &&
    event.sender === runnerWindow.webContents &&
    activeRequest &&
    payload?.requestId === activeRequest.id
  ) {
    const request = activeRequest;
    activeRequest = null;
    request.resolve(payload.result);
  }
});

ipcMain.on("cabinetnc-error", (event, payload) => {
  const requestId = payload && typeof payload === "object" ? payload.requestId : null;
  const message =
    payload && typeof payload === "object"
      ? payload.error
      : payload;
  if (
    runnerWindow &&
    event.sender === runnerWindow.webContents &&
    activeRequest &&
    (requestId == null || requestId === activeRequest.id)
  ) {
    const request = activeRequest;
    activeRequest = null;
    request.reject(new Error(message || "Deepnest renderer failed."));
  }
});

ipcMain.on("background-start", (_event, payload) => {
  if (!backgroundWindow || backgroundWindow.isDestroyed()) {
    failActive(new Error("Deepnest background renderer is unavailable."));
    return;
  }
  backgroundRequestIds.push(activeRequest?.id ?? null);
  backgroundWindow.webContents.send("background-start", payload);
});

ipcMain.on("background-response", (event, payload) => {
  if (
    backgroundWindow &&
    event.sender === backgroundWindow.webContents &&
    runnerWindow &&
    !runnerWindow.isDestroyed()
  ) {
    runnerWindow.webContents.send("background-response", {
      ...payload,
      __cabinetncRequestId: backgroundRequestIds.shift() ?? null,
    });
  }
});

ipcMain.on("background-progress", (event, payload) => {
  if (
    backgroundWindow &&
    event.sender === backgroundWindow.webContents &&
    runnerWindow &&
    !runnerWindow.isDestroyed()
  ) {
    runnerWindow.webContents.send("background-progress", payload);
  }
});

ipcMain.on("test", () => {
  // Deepnest's background renderer emits this diagnostic channel.
});

app.whenReady().then(async () => {
  if (!portFile) {
    throw new Error("Required argument missing: --port-file <path>");
  }
  const webPreferences = {
    contextIsolation: false,
    nodeIntegration: true,
    enableRemoteModule: true,
    sandbox: false,
  };

  backgroundWindow = new BrowserWindow({ show: false, webPreferences });
  runnerWindow = new BrowserWindow({ show: false, webPreferences });

  backgroundWindow.webContents.on("render-process-gone", (_event, details) => {
    fatal(`Deepnest background renderer exited: ${details.reason}`);
  });
  runnerWindow.webContents.on("render-process-gone", (_event, details) => {
    fatal(`Deepnest bridge renderer exited: ${details.reason}`);
  });

  backgroundWindow.webContents.once("did-finish-load", () => {
    backgroundReady = true;
  });

  await Promise.all([
    backgroundWindow.loadFile(path.join(vendorDir, "main", "background.html")),
    runnerWindow.loadFile(path.join(bridgeDir, "runner.html")),
  ]);
  await waitForWindows();
  const port = await listenOnLoopback();
  await writePortFile(port);
}).catch(fatal);

app.on("window-all-closed", () => {
  if (!shuttingDown) fatal("Deepnest windows closed unexpectedly.");
});
