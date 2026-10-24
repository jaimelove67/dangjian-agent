// Exercises the real React API adapters against the isolated, seeded FastAPI instance.
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { backend, request, saveSession, getSession, clearSession } from "../frontend/src/api.js";
import { roleApi } from "../frontend/src/role-api.js";

const base = new URL(process.env.DANGJIAN_SMOKE_URL || "http://127.0.0.1:18001");
assert.ok(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname), "Use a loopback test server.");
assert.equal(process.env.DANGJIAN_SMOKE_ALLOW_WRITES, "isolated", "Explicitly select the isolated test database.");
const password = process.env.DANGJIAN_SMOKE_PASSWORD;
assert.ok(password, "Set the synthetic bootstrap account password in the environment.");

const entries = new Map();
globalThis.sessionStorage = {
  getItem: (key) => entries.get(key) ?? null,
  setItem: (key, value) => entries.set(key, value),
  removeItem: (key) => entries.delete(key),
};
globalThis.window = new EventTarget();
const network = globalThis.fetch;
const calls = [];
globalThis.fetch = async (url, options) => {
  const target = new URL(url, base);
  assert.equal(target.origin, base.origin);
  const response = await network(target, options);
  calls.push({ path: target.pathname, method: options?.method || "GET", status: response.status });
  return response;
};
const passed = [];
async function login(username) {
  clearSession();
  const session = await backend.login(username, password);
  saveSession({ ...session, mode: "live" });
  assert.equal(session.user.tenant_id, username === "admin" ? "PLATFORM_TENANT" : "TEST_TENANT");
  return session;
}
const output = process.env.DANGJIAN_SMOKE_REPORT || "tmp/qa/backend-integration.json";
let status = "failed";

try {
  const health = await network(new URL("/api/v1/health/live", base));
  assert.equal(health.status, 200);
  await login("test-member");
  const before = await roleApi.archive();
  passed.push("real login, permissions and own-archive request");

  await login("test-organizer");
  const organizations = await backend.organizations();
  assert.ok(organizations.some((org) => org.id === "TEST_BRANCH"));
  const roster = await backend.members();
  let profile = before.profile || roster.items.find((row) => row.name === "本地联调合成党员");
  if (!profile) profile = await backend.createMember({
    name: "本地联调合成党员", org_unit_id: "TEST_BRANCH", current_stage: "member", materials: [], pending: 0,
  });
  await roleApi.linkAccount(profile.id, "test-member");
  passed.push("authorized roster creation and explicit account association");

  await login("test-member");
  const archive = await roleApi.archive();
  assert.equal(archive.profile.id, profile.id);
  const content = "本地联调合成学习记录，仅用于检查上传、下载与授权。";
  const file = new File([content], "联调学习记录.txt", { type: "text/plain" });
  const submission = {
    file, title: "本地联调学习记录", category: "study_note", description: "合成数据接口验收", submission_key: crypto.randomUUID(),
  };
  const material = await roleApi.submitMaterial(submission);
  const retry = await roleApi.submitMaterial(submission);
  assert.equal(retry.id, material.id);
  assert.equal(await (await roleApi.ownFile(material.id)).text(), content);
  assert.ok((await roleApi.ownMaterials()).items.some((row) => row.id === material.id));
  passed.push("personal upload, idempotent retry, persisted list and exact original download");

  await login("test-organizer");
  assert.ok((await roleApi.receivedMaterials(profile.id)).items.some((row) => row.id === material.id));
  assert.equal(await (await roleApi.receivedFile(profile.id, material.id)).text(), content);
  passed.push("authorized organizer receives and downloads the original");

  const overlength = await network(new URL("/api/v1/qa", base), {
    method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${getSession().tokens.access_token}` },
    body: JSON.stringify({ question: "问".repeat(501) }),
  });
  assert.equal(overlength.status, 422);
  passed.push("real QA schema rejects 501 characters without calling a model");

  await login("test-applicant");
  await assert.rejects(() => roleApi.ownFile(material.id), (error) => [403, 404].includes(error.status));
  await assert.rejects(() => backend.members(), (error) => error.status === 403);
  await assert.rejects(() => roleApi.receivedMaterials(profile.id), (error) => error.status === 403);
  passed.push("another personal account cannot access the roster or another person's original");
  await backend.logout();
  await assert.rejects(() => request("/auth/me"), (error) => error.status === 401);
  passed.push("logout revokes the actual backend session");

  await login("admin");
  const audit = await roleApi.audit({ tenant_id: "TEST_TENANT", action: "link_account" });
  assert.ok(audit.items.some((row) => row.resource_id === profile.id));
  passed.push("platform audit retains the explicit account association");
  status = "passed";
  console.log(JSON.stringify({ status: "passed", passed, requests: calls.length }, null, 2));
} finally {
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, JSON.stringify({ status, kind: "real local FastAPI, PostgreSQL and Redis; synthetic identities; no model calls", passed, calls }, null, 2));
  clearSession();
}
