// Runs Pyodide (CPython compiled to WebAssembly) and the real slowlens package off the main thread.
/* global importScripts, loadPyodide */
"use strict";

let pyodide = null;
let bridge = null;

function post(message) {
  self.postMessage(message);
}

async function init() {
  const cfg = await (await fetch("config.json")).json();
  importScripts(cfg.pyodideBase + "pyodide.js");
  pyodide = await loadPyodide({ indexURL: cfg.pyodideBase });
  const zip = await (await fetch("slowlens.zip")).arrayBuffer();
  pyodide.unpackArchive(zip, "zip", { extractDir: "/lib/slowlens-src" });
  pyodide.runPython("import sys; sys.path.insert(0, '/lib/slowlens-src')");
  const source = await (await fetch("bridge.py")).text();
  pyodide.FS.writeFile("/lib/slowlens-src/ql_bridge.py", source);
  bridge = pyodide.pyimport("ql_bridge");
  post({ type: "ready", version: pyodide.runPython("import slowlens; slowlens.__version__") });
}

function analyze(id, bytes, options) {
  pyodide.FS.writeFile(bridge.LOG_PATH, bytes);
  let proxy = null;
  try {
    const pyOptions = pyodide.toPy(options);
    proxy = bridge.analyze(pyOptions);
    const result = proxy.toJs({ dict_converter: Object.fromEntries });
    pyOptions.destroy();
    post({ type: "result", id, result });
  } finally {
    if (proxy) proxy.destroy();
    pyodide.FS.unlink(bridge.LOG_PATH);
  }
}

self.onmessage = (event) => {
  const { type, id, bytes, options } = event.data;
  if (type !== "analyze") return;
  try {
    analyze(id, bytes, options);
  } catch (error) {
    post({ type: "failure", id, message: String(error && error.message ? error.message : error) });
  }
};

init().catch((error) => post({ type: "fatal", message: String(error && error.message ? error.message : error) }));
