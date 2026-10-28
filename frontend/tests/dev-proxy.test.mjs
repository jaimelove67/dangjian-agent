import { test } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import net from "node:net";
import { once } from "node:events";
import { createServer as createViteServer } from "vite";
import viteConfig from "../vite.config.mjs";

async function listen(server) {
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  return `http://127.0.0.1:${server.address().port}`;
}

// Vite treats a falsy port (including 0) as "use the default 5173", which makes
// this test fail whenever a developer already has a dev server on that port.
async function freePort() {
  const probe = net.createServer();
  probe.listen(0, "127.0.0.1");
  await once(probe, "listening");
  const { port } = probe.address();
  await new Promise((resolve) => probe.close(resolve));
  return port;
}

function get(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { agent: false }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () =>
        resolve({
          status: response.statusCode,
          headers: response.headers,
          text: Buffer.concat(chunks).toString("utf8"),
        }),
      );
    });
    request.on("error", reject);
    request.setTimeout(5000, () => request.destroy(new Error("Proxy timeout")));
  });
}

async function startProxy(target) {
  const config = viteConfig({ mode: "test" });
  const server = await createViteServer({
    ...config,
    configFile: false,
    mode: "test",
    logLevel: "silent",
    optimizeDeps: { noDiscovery: true, include: [] },
    server: {
      ...config.server,
      host: "127.0.0.1",
      port: await freePort(),
      strictPort: true,
      hmr: false,
      watch: null,
      warmup: { clientFiles: [] },
      proxy: {
        "/api": { ...config.server.proxy["/api"], target },
      },
    },
  });
  await server.listen();
  return {
    server,
    url: `http://127.0.0.1:${server.httpServer.address().port}`,
  };
}

test("the real Vite proxy diagnoses an unavailable backend for API paths", async (t) => {
  const unavailable = http.createServer();
  const target = await listen(unavailable);
  await new Promise((resolve) => unavailable.close(resolve));
  const proxy = await startProxy(target);
  t.after(() => proxy.server.close());

  for (const path of ["/api/v1/health/live", "/api/diagnostics"]) {
    const response = await get(proxy.url + path);
    assert.equal(response.status, 503, path);
    assert.match(response.headers["content-type"], /^application\/json\b/);
    assert.equal(
      JSON.parse(response.text).message,
      "系统服务暂时无法连接，请稍后重试；如持续失败，请联系管理员。",
    );
  }
});

test("the real Vite proxy preserves a backend HTTP 500 response", async (t) => {
  const body = JSON.stringify({
    code: 50001,
    message: "后端业务异常",
    trace_id: "backend-trace-test",
  });
  const upstream = http.createServer((request, response) => {
    assert.equal(request.url, "/api/v1/health/live?source=proxy-test");
    response.writeHead(500, {
      "Content-Type": "application/json; charset=utf-8",
      "X-Request-Id": "backend-trace-test",
    });
    response.end(body);
  });
  const target = await listen(upstream);
  t.after(() => new Promise((resolve) => upstream.close(resolve)));
  const proxy = await startProxy(target);
  t.after(() => proxy.server.close());

  const response = await get(
    proxy.url + "/api/v1/health/live?source=proxy-test",
  );
  assert.equal(response.status, 500);
  assert.equal(response.text, body);
  assert.equal(response.headers["x-request-id"], "backend-trace-test");
});
