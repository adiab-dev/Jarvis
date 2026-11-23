import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const backendRoot = join(projectRoot, "backend");
const localPython = join(
  backendRoot,
  ".venv",
  process.platform === "win32" ? "Scripts" : "bin",
  process.platform === "win32" ? "python.exe" : "python",
);
const viteScript = join(projectRoot, "node_modules", "vite", "bin", "vite.js");

let backendProcess;
let viteProcess;
let stopping = false;
let triedPythonFallback = false;

function spawnProcess(command, args, options = {}) {
  return spawn(command, args, {
    cwd: options.cwd ?? projectRoot,
    env: process.env,
    stdio: "inherit",
    windowsHide: true,
  });
}

function stopProcessTree(child) {
  if (!child?.pid) return;
  if (process.platform === "win32") {
    spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], {
      stdio: "ignore",
      windowsHide: true,
    });
  } else {
    child.kill("SIGTERM");
  }
}

function stopAll(exitCode = 0) {
  if (stopping) return;
  stopping = true;
  stopProcessTree(backendProcess);
  stopProcessTree(viteProcess);
  process.exitCode = exitCode;
  setTimeout(() => process.exit(exitCode), 300).unref();
}

function startBackend(command, args) {
  backendProcess = spawnProcess(command, args, { cwd: backendRoot });
  backendProcess.on("error", (error) => {
    if (command === "py" && !triedPythonFallback) {
      triedPythonFallback = true;
      console.warn("Python launcher 'py' was not found; trying 'python' instead.");
      startBackend("python", ["main.py"]);
      return;
    }
    console.error(`Could not start the Jarvis Python server: ${error.message}`);
  });
  backendProcess.on("exit", (code) => {
    if (stopping || code === 0) return;
    console.error(
      "The Jarvis Python server stopped. Install its packages in backend/.venv with: python -m pip install -r backend/requirements.txt",
    );
  });
}

if (existsSync(localPython)) {
  console.log("Starting the Jarvis Python server from backend/.venv...");
  startBackend(localPython, ["main.py"]);
} else if (process.platform === "win32") {
  console.log("Starting the Jarvis Python server with the Windows Python launcher...");
  startBackend("py", ["-3", "main.py"]);
} else {
  console.log("Starting the Jarvis Python server with python3...");
  startBackend("python3", ["main.py"]);
}

console.log("Starting the Vite frontend...");
viteProcess = spawnProcess(process.execPath, [viteScript]);
viteProcess.on("error", (error) => {
  console.error(`Could not start Vite: ${error.message}`);
  stopAll(1);
});
viteProcess.on("exit", (code) => stopAll(code ?? 0));

process.on("SIGINT", () => stopAll(0));
process.on("SIGTERM", () => stopAll(0));
