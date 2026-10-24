import { spawn, execFile } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { createServer } from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseEnv, promisify } from "node:util";

const root = fileURLToPath(new URL("..", import.meta.url));
const backendDir = path.join(root, "backend");
const frontendDir = path.join(root, "frontend");

export function backendEnvironment(inherited = process.env, directory = backendDir) {
  const envFile = path.join(directory, ".env");
  return { ...(existsSync(envFile) ? parseEnv(readFileSync(envFile, "utf8")) : {}), ...inherited };
}

export function backendAddress(env) {
  const port = Number(env.PORT || env.APP_PORT || 8000);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("APP_PORT/PORT must be an integer from 1 to 65535.");
  }
  return { host: "127.0.0.1", port, url: `http://127.0.0.1:${port}` };
}

export function frontendEnvironment(inherited, backendUrl) {
  return backendUrl
    ? { ...inherited, VITE_DATA_MODE: "live", VITE_API_BASE_URL: "/api/v1", VITE_API_TARGET: backendUrl }
    : { ...inherited };
}

export async function checkBackendPort({ host, port }) {
  const probe = createServer();
  await new Promise((resolve, reject) => {
    probe.once("error", () => reject(new Error(`Backend port ${port} is already in use or unavailable; choose another APP_PORT.`)));
    probe.listen({ host, port, exclusive: true }, resolve);
  });
  await new Promise((resolve, reject) => probe.close(error => error ? reject(error) : resolve()));
}

function pythonExecutable(env) {
  if (env.PARTY_PYTHON) return env.PARTY_PYTHON;
  for (const venv of [".venv", ".venv-runtime"]) {
    const executable = path.join(backendDir, venv, process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
    if (existsSync(executable)) return executable;
  }
  return process.platform === "win32" ? "python" : "python3";
}

async function stopChild(child) {
  if (child.exitCode !== null || child.signalCode || !child.pid) return;
  if (process.platform === "win32") {
    // Python virtual-environment launchers can have their own child process.
    await promisify(execFile)("taskkill", ["/PID", String(child.pid), "/T", "/F"]).catch(() => {});
  } else {
    child.kill("SIGTERM");
  }
}

async function waitForBackend(url, stopped) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    if (stopped()) throw new Error("Backend exited before its health check succeeded.");
    try {
      const response = await fetch(`${url}/api/v1/health/live`, { signal: AbortSignal.timeout(1000) });
      if (response.ok && (await response.json()).status === "alive") return;
    } catch { /* Retry while the owned process is starting. */ }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error("Backend startup timed out; inspect the backend output above.");
}

export async function run(mode, args = []) {
  if (!["frontend", "backend", "all"].includes(mode)) {
    throw new Error("Usage: node scripts/dev.mjs [frontend|backend|all] [Vite arguments]");
  }
  const children = [];
  let stopping = false;
  let finished;
  const done = new Promise(resolve => { finished = resolve; });
  async function shutdown(code) {
    if (stopping) return;
    stopping = true;
    await Promise.all(children.map(stopChild));
    finished(code);
  }
  const interrupted = () => { void shutdown(130); };
  const terminated = () => { void shutdown(143); };
  process.once("SIGINT", interrupted);
  process.once("SIGTERM", terminated);
  function start(command, commandArgs, cwd, env) {
    const child = spawn(command, commandArgs, { cwd, env, stdio: "inherit", windowsHide: true });
    children.push(child);
    child.once("error", () => {
      console.error(`Cannot start ${cwd === backendDir ? "backend; install Python requirements and check PARTY_PYTHON" : "frontend; run npm install"}.`);
      void shutdown(1);
    });
    child.once("exit", code => { void shutdown(code ?? 1); });
    return child;
  }
  try {
    let address;
    if (mode !== "frontend") {
      const env = backendEnvironment();
      address = backendAddress(env);
      await checkBackendPort(address);
      if (stopping) return await done;
      const backend = start(pythonExecutable(env), ["-m", "uvicorn", "app.main:app", "--host", address.host, "--port", String(address.port)], backendDir, env);
      await waitForBackend(address.url, () => stopping || backend.exitCode !== null || Boolean(backend.signalCode));
      console.log(`Backend: ${address.url} (readiness: ${address.url}/api/v1/health/ready)`);
    }
    if (mode !== "backend" && !stopping) {
      const frontendRequire = createRequire(path.join(frontendDir, "package.json"));
      const vite = path.join(path.dirname(frontendRequire.resolve("vite/package.json")), "bin/vite.js");
      start(process.execPath, [vite, ...args], frontendDir, frontendEnvironment(process.env, address?.url));
    }
    return await done;
  } catch (error) {
    await shutdown(1);
    throw error;
  } finally {
    process.removeListener("SIGINT", interrupted);
    process.removeListener("SIGTERM", terminated);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  run(process.argv[2] || "frontend", process.argv.slice(3))
    .then(code => { process.exitCode = code; })
    .catch(error => { console.error(error.message); process.exitCode = 1; });
}
