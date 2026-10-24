import assert from "node:assert/strict";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { createServer } from "node:net";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { backendAddress, backendEnvironment, frontendEnvironment, checkBackendPort } from "../scripts/dev.mjs";

test("backend loads only its own env file and inherited settings take precedence", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "dangjian-dev-"));
  try {
    await writeFile(path.join(directory, ".env"), 'APP_PORT=18001\nSECRET_KEY="server-only"\n');
    const inherited = { APP_PORT: "18002", PATH: "example" };
    const backend = backendEnvironment(inherited, directory);
    assert.equal(backend.SECRET_KEY, "server-only");
    assert.equal(backendAddress(backend).url, "http://127.0.0.1:18002");
    assert.deepEqual(frontendEnvironment(inherited, backendAddress(backend).url), {
      APP_PORT: "18002", PATH: "example", VITE_DATA_MODE: "live",
      VITE_API_BASE_URL: "/api/v1", VITE_API_TARGET: "http://127.0.0.1:18002",
    });
    assert.equal(inherited.SECRET_KEY, undefined);
  } finally {
    assert.equal(path.dirname(directory), os.tmpdir());
    await rm(directory, { recursive: true, force: true });
  }
});

test("backend port validation respects the existing PORT alias", () => {
  assert.equal(backendAddress({ PORT: "18003", APP_PORT: "18001" }).port, 18003);
  for (const APP_PORT of ["0", "-1", "65536", "8000.5", "not-a-port"]) {
    assert.throws(() => backendAddress({ APP_PORT }), /APP_PORT/);
  }
});

test("an occupied backend port is rejected without stopping its existing listener", async () => {
  const listener = createServer();
  await new Promise(resolve => listener.listen(0, "127.0.0.1", resolve));
  try {
    await assert.rejects(checkBackendPort({ host: "127.0.0.1", port: listener.address().port }), /already in use/);
    assert.equal(listener.listening, true);
  } finally {
    await new Promise(resolve => listener.close(resolve));
  }
});
