import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { platformOpsApi } from "../src/platform-ops-api.js";
import { request, saveSession, getSession } from "../src/api.js";

describe("platform health adapter", () => {
  const originalFetch = globalThis.fetch;
  const originalStorage = globalThis.sessionStorage;
  const originalWindow = globalThis.window;
  const entries = new Map(),
    events = [];
  const session = {
    user: { id: "platform-1" },
    tokens: { access_token: "expired", refresh_token: "refresh-1" },
  };
  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  beforeEach(() => {
    entries.clear();
    events.length = 0;
    globalThis.sessionStorage = {
      getItem: (key) => entries.get(key) || null,
      setItem: (key, value) => entries.set(key, value),
      removeItem: (key) => entries.delete(key),
    };
    globalThis.window = { dispatchEvent: (event) => events.push(event.type) };
    saveSession(session);
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    globalThis.sessionStorage = originalStorage;
    globalThis.window = originalWindow;
  });

  test("platform health refresh shares authentication and preserves raw ready/503 diagnostics", async () => {
    for (const diagnostic of [
      { http: 200, body: { status: "ready", checks: { database: "healthy" } } },
      {
        http: 503,
        body: {
          status: "not_ready",
          checks: { database: "unhealthy", model_warm: "unverified" },
        },
      },
    ]) {
      saveSession(session);
      let refreshed = 0;
      globalThis.fetch = async (url, options) => {
        assert.equal(
          options.rawJson,
          undefined,
          "client-only options are not sent to fetch",
        );
        if (url === "/api/v1/auth/refresh") {
          refreshed++;
          assert.equal(options.headers.Authorization, "Bearer refresh-1");
          return json({
            code: 0,
            data: { access_token: "valid", refresh_token: "refresh-2" },
          });
        }
        assert.equal(url, "/api/v1/admin/health/ready");
        return options.headers.Authorization === "Bearer valid"
          ? json(diagnostic.body, diagnostic.http)
          : json({ code: 40101, message: "expired" }, 401);
      };
      assert.deepEqual(await platformOpsApi.health(), diagnostic.body);
      assert.equal(refreshed, 1);
      assert.equal(getSession().tokens.access_token, "valid");
    }
    globalThis.fetch = async () =>
      json({ status: "not_ready", checks: { database: "unhealthy" } }, 503);
    await assert.rejects(
      request("/member/roster", { rawJson: true, acceptNotReady: true }),
      (error) => error.status === 503,
      "health exception must not apply to business APIs",
    );
    assert.deepEqual(events, []);
  });

  test("platform health discards responses across account switches during refresh or JSON parsing", async () => {
    const other = {
      user: { id: "platform-2" },
      tokens: { access_token: "other", refresh_token: "other-refresh" },
    };
    let healthCalls = 0;
    globalThis.fetch = async (url) => {
      if (url === "/api/v1/auth/refresh") {
        saveSession(other);
        return json({
          code: 0,
          data: {
            access_token: "old-account-new-token",
            refresh_token: "refresh-2",
          },
        });
      }
      healthCalls++;
      return json({ message: "expired" }, 401);
    };
    await assert.rejects(platformOpsApi.health(), /会话已变更/);
    assert.equal(
      healthCalls,
      1,
      "must not repeat the old request under a new account",
    );
    assert.equal(getSession().user.id, "platform-2");
    assert.deepEqual(events, [], "must not expire the new account");
    saveSession(session);
    globalThis.fetch = async () => ({
      ok: true,
      status: 200,
      json: async () => {
        saveSession(other);
        return { status: "ready", checks: { database: "healthy" } };
      },
    });
    await assert.rejects(platformOpsApi.health(), /会话已变更/);
    assert.equal(getSession().user.id, "platform-2");
  });
});
