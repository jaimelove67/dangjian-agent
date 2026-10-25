import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { request, saveSession, getSession, ApiError, backend } from "../src/api.js";
import { roleApi } from "../src/role-api.js";
import { adoptMaterialSuggestions, clearMaterialSuggestions } from "../src/material-draft.js";
import { platformIdentityApi } from "../src/platform-identity-api.js";

test("platform attribute edits use a tenant-scoped PATCH without changing login or archive identity", async () => {
  const update = {
    name: "核验姓名",
    role: "member",
    org_unit_id: "branch-1",
    is_active: true,
  };
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/admin/users/account%2F1?tenant_id=school-1");
    assert.equal(options.method, "PATCH");
    assert.deepEqual(JSON.parse(options.body), update);
    return ok({ id: "account/1", ...update });
  };
  await platformIdentityApi.updateUser("school-1", "account/1", update);
});

test("administrator password edits send only the new password through the scoped update contract", async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/admin/users/school-account?tenant_id=school-1");
    assert.equal(options.method, "PATCH");
    assert.deepEqual(JSON.parse(options.body), {
      password: "Test-contract-2026",
    });
    return ok({ id: "school-account", name: "本校账号" });
  };
  await platformIdentityApi.updateUser("school-1", "school-account", {
    password: "Test-contract-2026",
  });
});
test("explicit account linking sends only the verified username", async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/member/roster/profile-1/account");
    assert.equal(options.method, "PUT");
    assert.deepEqual(JSON.parse(options.body), { username: "applicant-1" });
    return ok({ id: "profile-1" });
  };
  await roleApi.linkAccount("profile-1", "applicant-1");
});

test("roster template and import use the school-scoped Excel contract", async () => {
  const file = new File(["名册"], "党员名册.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  globalThis.fetch = async (url, options) => {
    if (url === "/api/v1/member/roster/template") {
      assert.equal(options.download, true);
      return new Response("xlsx-template", { status: 200 });
    }
    assert.equal(url, "/api/v1/member/roster/import");
    assert.equal(options.method, "POST");
    assert.equal(options.body.get("file"), file);
    assert.equal(options.body.get("source_note"), "校内台账导出 2026-10-25");
    assert.equal(options.body.get("dry_run"), "true");
    return ok({ total_rows: 1, created: 1, skipped: 0, failed: 0, rows: [] });
  };
  const template = await backend.rosterTemplate();
  assert.equal(await template.text(), "xlsx-template");
  const report = await backend.importRoster({
    file,
    sourceNote: "校内台账导出 2026-10-25",
  });
  assert.equal(report.created, 1);
});

const originalFetch = globalThis.fetch;
const entries = new Map();
const events = [];
globalThis.sessionStorage = {
  getItem: (key) => entries.get(key) || null,
  setItem: (key, value) => entries.set(key, value),
  removeItem: (key) => entries.delete(key),
};
globalThis.window = { dispatchEvent: (event) => events.push(event.type) };
const session = {
  user: { id: "account-1", username: "organizer" },
  permissions: ["member.query"],
  tokens: { access_token: "access-old", refresh_token: "refresh-one" },
};
const ok = (data) =>
  new Response(
    JSON.stringify({ code: 0, message: "ok", data, trace_id: "trace-test" }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );

test("material previews use authorized multipart endpoints and do not send cloud consent", async () => {
  const file = new File(["思想汇报"], "材料.txt");
  for (const profile of [undefined, "profile/1"]) {
    globalThis.fetch = async (url, options) => {
      assert.equal(url, profile ? "/api/v1/member-full/profiles/profile%2F1/materials/preview" : "/api/v1/member/self/materials/preview");
      assert.equal(options.method, "POST");
      assert.deepEqual([...options.body.keys()], ["file"]);
      return ok({ fields: {} });
    };
    await roleApi.previewMaterial(file, profile);
  }
});

test("material suggestions preserve manual edits and clear only adopted values on file change", () => {
  const { draft, adopted } = adoptMaterialSuggestions({ title: "人工标题", category: "", description: "" }, { title: "提取标题", category: "thought_report", description: "原文说明", subject_name: "不写入档案" }, ["title", "category", "description"]);
  assert.deepEqual(draft, { title: "人工标题", category: "thought_report", description: "原文说明" });
  assert.deepEqual(clearMaterialSuggestions({ ...draft, description: "人工修改说明" }, adopted), { title: "人工标题", category: "", description: "人工修改说明" });
});

test("development original upload preserves confirmed metadata without cloud processing", async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/member-full/profiles/profile-1/materials/scan");
    assert.equal(options.body.get("file_version"), "v2");
    assert.equal(options.body.get("submit_date"), "2026-10-01");
    assert.equal(options.body.get("reason"), "人工登记依据");
    assert.equal(options.body.has("cloud_ocr"), false);
    return ok({ review_status: "pending" });
  };
  await roleApi.archiveMaterial("profile-1", { file: new File(["原文"], "材料.txt"), material_type: "思想汇报", file_version: "v2", submit_date: "2026-10-01", reason: "人工登记依据" });
});

test("QA accepts 500 Unicode characters, trims surrounding space and keeps the public request scope", async () => {
  const question = "问".repeat(498) + "😀😀";
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/qa");
    assert.deepEqual(JSON.parse(options.body), {
      question,
      session_id: "session-1",
      data_level: "public",
      use_reranker: true,
      top_k: 5,
    });
    return ok({ answer: "已核验的接口回答", citations: [] });
  };
  await backend.ask({ question: `  ${question}\n`, session_id: "session-1" });
});

test("QA rejects blank and overlength questions before sending any request", async () => {
  let requests = 0;
  globalThis.fetch = async () => {
    requests += 1;
    return ok({ answer: "不应发送请求" });
  };
  for (const question of ["问".repeat(501), "😀".repeat(501)]) {
    await assert.rejects(() => backend.ask({ question }), /500/);
  }
  await assert.rejects(() => backend.ask({ question: " \n\t" }), /请输入问题/);
  assert.equal(requests, 0);
});
test("personal submission sends original file and stable idempotency key as multipart, without owner identifiers", async () => {
  const file = new File(["个人学习记录"], "学习记录.txt", {
    type: "text/plain",
  });
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/member/self/materials");
    assert.equal(options.method, "POST");
    assert.ok(options.body instanceof FormData);
    assert.equal(options.headers["Content-Type"], undefined);
    assert.deepEqual(
      [...options.body.keys()],
      ["file", "title", "category", "description", "submission_key"],
    );
    assert.equal(options.body.get("submission_key"), "retry-stable-uuid");
    assert.equal(await options.body.get("file").text(), "个人学习记录");
    return ok({ id: "material-1", status: "submitted" });
  };
  await roleApi.submitMaterial({
    file,
    title: "学习记录",
    category: "study_note",
    description: "说明",
    submission_key: "retry-stable-uuid",
  });
});
test("received originals use the explicit roster and material identifiers", async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(
      url,
      "/api/v1/member/roster/profile%2F1/materials/material%201/file",
    );
    return new Response("private original", {
      headers: { "Content-Type": "application/octet-stream" },
    });
  };
  const result = await roleApi.receivedFile("profile/1", "material 1");
  assert.equal(await result.text(), "private original");
});
test("meeting review sends expected revision and explicit decision; submission omits decision", async () => {
  const bodies = [];
  globalThis.fetch = async (url, options) => {
    bodies.push({ url, body: JSON.parse(options.body) });
    return ok({ id: "meeting-1" });
  };
  await roleApi.meetingAction("meeting-1", "submit", 3, "人工核对提交");
  await roleApi.meetingAction(
    "meeting-1",
    "review",
    4,
    "独立审核意见",
    "rejected",
  );
  assert.deepEqual(bodies[0], {
    url: "/api/v1/meeting/records/meeting-1/submit",
    body: { expected_revision: 3, reason: "人工核对提交" },
  });
  assert.deepEqual(bodies[1].body, {
    expected_revision: 4,
    reason: "独立审核意见",
    decision: "rejected",
  });
});
test("governance decisions preserve source version and returned decision", async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/admin/reviews/review-1/decision");
    assert.deepEqual(JSON.parse(options.body), {
      decision: "returned",
      source_version: "a".repeat(64),
      opinion: "请核对来源",
    });
    return ok({});
  };
  await roleApi.decideReview("review-1", {
    decision: "returned",
    source_version: "a".repeat(64),
    opinion: "请核对来源",
  });
});
test("account creation and manual transition preserve the reference backend payloads", async () => {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    calls.push({ url, body: JSON.parse(options.body) });
    return ok({ id: "new" });
  };
  const account = {
    username: "new_account",
    name: "新账号",
    password: "test-only-password",
    role: "member",
    org_unit_id: "branch-1",
    member_id: "profile-1",
  };
  await roleApi.createAccount(account);
  const transition = {
    target_stage: "activist",
    decision_date: "2026-10-23",
    basis: "支部决定",
    opinion: "组织人工登记",
  };
  await roleApi.transition("profile-1", transition);
  assert.deepEqual(calls, [
    { url: "/api/v1/admin/users", body: account },
    {
      url: "/api/v1/member-full/profiles/profile-1/transition",
      body: transition,
    },
  ]);
});
beforeEach(() => {
  entries.clear();
  events.length = 0;
  saveSession(session);
});
afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("API client unwraps the actual backend envelope and sends bearer authentication", async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/member/roster");
    assert.equal(options.headers.Authorization, "Bearer access-old");
    return ok({ items: [] });
  };
  assert.deepEqual(await request("/member/roster"), { items: [] });
});
test("business errors preserve the message and request trace identifier", async () => {
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        code: 40302,
        message: "当前组织不在授权范围",
        trace_id: "trace-scope",
      }),
      { status: 403 },
    );
  await assert.rejects(
    request("/member/roster"),
    (error) =>
      error instanceof ApiError &&
      error.status === 403 &&
      error.traceId === "trace-scope" &&
      error.message.includes("授权范围"),
  );
});
test("concurrent unauthorized requests share a refresh and retry using the new access token", async () => {
  let refreshCount = 0;
  globalThis.fetch = async (url, options) => {
    if (url.endsWith("/auth/refresh")) {
      refreshCount++;
      assert.equal(options.headers.Authorization, "Bearer refresh-one");
      await new Promise((resolve) => setTimeout(resolve, 5));
      return ok({ access_token: "access-new", refresh_token: "refresh-two" });
    }
    return options.headers.Authorization === "Bearer access-new"
      ? ok({ authorized: true })
      : new Response(JSON.stringify({ code: 40101, message: "令牌已失效" }), {
          status: 401,
        });
  };
  const results = await Promise.all([
    request("/member/roster"),
    request("/meeting/records"),
  ]);
  assert.ok(results.every((result) => result.authorized));
  assert.equal(refreshCount, 1);
  assert.equal(getSession().tokens.access_token, "access-new");
});
test("responses from a previous account cannot populate the new account workspace", async () => {
  globalThis.fetch = async () => {
    saveSession({ ...session, user: { id: "account-2", username: "other" } });
    return ok({ private: "previous-user-data" });
  };
  await assert.rejects(request("/member/self/archive"), /会话已变更/);
  assert.equal(getSession().user.id, "account-2");
  assert.deepEqual(events, []);
});
test("an expired session without refresh credentials is cleared and emits the sign-in event", async () => {
  saveSession({ ...session, tokens: { access_token: "access-old" } });
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ code: 40101, message: "登录已过期" }), {
      status: 401,
    });
  await assert.rejects(
    request("/member/roster"),
    (error) => error.status === 401,
  );
  assert.equal(getSession(), null);
  assert.deepEqual(events, ["dangjian:expired"]);
});
test("network failure reports a connection error without returning fabricated data", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("Network unavailable");
  };
  await assert.rejects(request("/meeting/records"), /系统服务暂时无法连接/);
});
