import { test } from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import {
  accountPasswordChange,
  createDemoPasswordService,
  PASSWORD_STORAGE_KEY,
} from "../src/password-security.js";
import {
  PLATFORM_NAV_SPEC,
  PLATFORM_ROUTES,
  demoSession,
  canAccess,
  scopedMembers,
  scopedMeetings,
  scopedOrganizations,
  demoAccountAvailable,
  normalizeDemoSession,
  sessionForAccount,
} from "../src/roles.js";
import { extendRoleData } from "../src/role-data.js";
import { buildInitialData } from "../src/data.js";
import { extendPlatformData, platformSummary } from "../src/platform-data.js";
import { validatePlatformConfig } from "../src/platform-ops-api.js";
import {
  validateAdminChange,
  validSchoolAdmin,
  accountRolesForTenant,
  validateAccountUpdate,
} from "../src/platform-identity-api.js";
import { validateMaterialFile } from "../src/material-validation.js";
const fixture = () => extendRoleData(buildInitialData());

function passwordFixture() {
  const data = fixture(),
    saved = new Map();
  let current = demoSession("school");
  const service = createDemoPasswordService({
    storage: {
      getItem: (key) => saved.get(key) || null,
      setItem: (key, value) => saved.set(key, value),
    },
    crypto: webcrypto,
    lock: async (_name, run) => run(),
    directory: () => data,
    currentSession: () => current,
  });
  return {
    data,
    saved,
    service,
    login(id) {
      const account = data.accounts.find((a) => a.id === id);
      current = sessionForAccount(account, service.revision(account));
      return account;
    },
  };
}

test("account password fields preserve blanks and validate confirmation and encoded length", () => {
  const form = (password = "", confirmation = password) =>
    new Map([
      ["password", password],
      ["password_confirmation", confirmation],
    ]);
  assert.equal(accountPasswordChange(form()), undefined);
  assert.equal(accountPasswordChange(form("secret-test-1")), "secret-test-1");
  assert.equal(accountPasswordChange(form("密".repeat(24))), "密".repeat(24));
  assert.equal(accountPasswordChange(form("🔐".repeat(8))), "🔐".repeat(8));
  for (const fields of [
    form("short"),
    form("secret-test-1", "different"),
    form("", "secret-test-1"),
    form("密".repeat(25)),
    form("🔐".repeat(4)),
    form(" secret-test-1 "),
  ])
    assert.throws(() => accountPasswordChange(fields));
  assert.throws(
    () => accountPasswordChange(form(), { required: true }),
    /至少8位/,
  );
});

test("school administrator password edits change login verification without storing plaintext or consuming self-service allowance", async () => {
  const { data, saved, service, login } = passwordFixture();
  const actor = login("demo-school"),
    target = data.accounts.find((a) => a.id === "demo-teacher");
  const password = "School-test-2026";
  await service.setPassword(actor, target, {
    password,
    confirmation: password,
  });
  assert.equal((await service.verify(target, "123456")).valid, false);
  assert.deepEqual(await service.verify(target, password), {
    valid: true,
    version: 1,
  });
  assert.equal(saved.get(PASSWORD_STORAGE_KEY).includes(password), false);
  assert.equal(JSON.stringify(data).includes(password), false);
  login(target.id);
  assert.equal(service.own(target).used, false);
  await service.change(target, {
    current: password,
    password: "Self-test-2026",
    confirmation: "Self-test-2026",
  });
  login(target.id);
  assert.equal(service.own(target).used, true);
  await service.apply(target, "需要重新设置账号密码");
  login(actor.id);
  await service.setPassword(actor, target, {
    password: "Updated-test-2026",
    confirmation: "Updated-test-2026",
  });
  login(target.id);
  assert.equal(service.own(target).used, true);
  assert.equal(service.own(target).canChange, false);
  assert.equal(service.own(target).history[0].status, "cancelled");
  assert.equal((await service.verify(target, "Self-test-2026")).valid, false);
});

test("password administration rejects foreign schools, privilege changes and unauthorized actors without writing credentials", async () => {
  const { data, saved, service, login } = passwordFixture();
  const actor = login("demo-school"),
    target = data.accounts.find((a) => a.id === "demo-student");
  data.tenants.push({ id: "foreign-school", is_active: true });
  data.accounts.push({
    ...target,
    id: "foreign-user",
    tenant_id: "foreign-school",
  });
  const fields = {
    password: "Security-test-2026",
    confirmation: "Security-test-2026",
  };
  for (const other of [
    data.accounts.at(-1),
    data.accounts.find((a) => a.id === "demo-platform"),
  ])
    await assert.rejects(service.setPassword(actor, other, fields), /本校/);
  await assert.rejects(
    service.setPassword(actor, target, {
      ...fields,
      confirmation: "incorrect",
    }),
    /不一致/,
  );
  assert.equal(saved.has(PASSWORD_STORAGE_KEY), false);
  const department = login("demo-department");
  await assert.rejects(
    service.setPassword(department, target, fields),
    /管理员/,
  );
  const platform = login("demo-platform");
  await service.setPassword(platform, data.accounts.at(-1), fields);
  assert.equal(
    (await service.verify(data.accounts.at(-1), fields.password)).valid,
    true,
  );
});

test("editing the current administrator password invalidates the old session and preserves its privileges", async () => {
  const { service, login } = passwordFixture(),
    actor = login("demo-school");
  await service.setPassword(actor, actor, {
    password: "Admin-test-2026",
    confirmation: "Admin-test-2026",
  });
  await assert.rejects(
    service.setPassword(actor, actor, {
      password: "Again-test-2026",
      confirmation: "Again-test-2026",
    }),
    /会话已失效/,
  );
  assert.equal(actor.role, "school_admin");
  login(actor.id);
  assert.equal((await service.verify(actor, "Admin-test-2026")).valid, true);
});

test("administrators can prepare a new password for an inactive account without enabling it", async () => {
  const { data, service, login } = passwordFixture(),
    actor = login("demo-school");
  const target = data.accounts.find((a) => a.id === "demo-student");
  target.is_active = false;
  await service.setPassword(actor, target, {
    password: "Inactive-test-2026",
    confirmation: "Inactive-test-2026",
  });
  assert.equal(target.is_active, false);
  await assert.rejects(service.verify(target, "Inactive-test-2026"), /不可用/);
  target.is_active = true;
  assert.equal(
    (await service.verify(target, "Inactive-test-2026")).valid,
    true,
  );
});

function editContext(data, tenantId = "school-1") {
  return {
    tenant: data.tenants.find((t) => t.id === tenantId),
    accounts: data.accounts,
    orgs: [
      { id: tenantId, org_type: "school" },
      { id: "dept-10", org_type: "department" },
      { id: "test-branch", org_type: "branch" },
    ],
  };
}

test("platform can edit personal accounts while administrator creation retains its role scope", () => {
  const data = fixture(),
    actor = demoSession("platform").user,
    context = editContext(data);
  assert.ok(accountRolesForTenant(context.tenant).includes("member"));
  assert.ok(accountRolesForTenant(context.tenant).includes("applicant"));
  assert.equal(
    accountRolesForTenant(context.tenant, { create: true }).includes("member"),
    false,
  );
  for (const role of ["member", "applicant"]) {
    const account = {
      ...data.accounts.find((a) => a.role === role),
      org_unit_id: "test-branch",
    };
    assert.doesNotThrow(() =>
      validateAccountUpdate(
        actor,
        account,
        {
          name: "编辑后的姓名",
          role,
          org_unit_id: "test-branch",
          is_active: false,
        },
        context,
      ),
    );
    assert.ok(account.profile_id);
    assert.equal(account.is_active, true);
  }
});

test("account edits reject foreign tenants, incompatible organizations and platform roles in a school", () => {
  const data = fixture(),
    actor = demoSession("platform").user,
    context = editContext(data);
  const account = data.accounts.find((a) => a.id === "demo-organizer");
  assert.throws(
    () =>
      validateAccountUpdate(
        actor,
        { ...account, tenant_id: "school-2" },
        { name: "修改" },
        context,
      ),
    /当前管理租户/,
  );
  assert.throws(
    () =>
      validateAccountUpdate(
        actor,
        account,
        { role: "system_admin", org_unit_id: null },
        context,
      ),
    /该租户/,
  );
  assert.throws(
    () =>
      validateAccountUpdate(
        actor,
        account,
        { role: "department_admin", org_unit_id: "test-branch" },
        context,
      ),
    /组织范围/,
  );
  assert.throws(
    () =>
      validateAccountUpdate(
        actor,
        account,
        { role: "organizer", org_unit_id: "foreign-branch" },
        context,
      ),
    /组织范围/,
  );
  assert.doesNotThrow(() =>
    validateAccountUpdate(
      actor,
      account,
      { role: "department_admin", org_unit_id: "dept-10" },
      context,
    ),
  );
  assert.doesNotThrow(() =>
    validateAccountUpdate(
      actor,
      account,
      { role: "organizer", org_unit_id: "dept-10" },
      context,
    ),
  );
  assert.throws(
    () =>
      validateAccountUpdate(
        actor,
        account,
        { role: "organizer", org_unit_id: "test-branch" },
        {
          ...context,
          orgs: context.orgs.map((org) =>
            org.id === "test-branch" ? { ...org, is_active: false } : org,
          ),
        },
      ),
    /组织范围/,
  );
  assert.doesNotThrow(() =>
    validateAccountUpdate(
      demoSession("school").user,
      account,
      { name: "修改" },
      context,
    ),
  );
});

test("school account editors stay within their own school and preserve their current privileges", () => {
  const data = fixture(),
    actor = demoSession("school").user,
    context = editContext(data);
  const account = data.accounts.find((a) => a.id === "demo-student");
  assert.doesNotThrow(() =>
    validateAccountUpdate(
      actor,
      account,
      { name: "本校账号", is_active: false },
      context,
    ),
  );
  assert.doesNotThrow(() =>
    validateAccountUpdate(
      actor,
      actor,
      { name: "校级值班员", password: "example-test-password" },
      context,
    ),
  );
  for (const changes of [{ role: "system_admin" }, { tenant_id: "school-2" }])
    assert.throws(
      () => validateAccountUpdate(actor, account, changes, context),
      /本校|租户/,
    );
  assert.throws(
    () =>
      validateAccountUpdate(
        actor,
        { ...account, tenant_id: "school-2" },
        { name: "跨校" },
        { ...context, tenant: { ...context.tenant, id: "school-2" } },
      ),
    /本校/,
  );
  for (const changes of [
    { is_active: false },
    { role: "department_admin" },
    { org_unit_id: "dept-10" },
  ])
    assert.throws(
      () => validateAccountUpdate(actor, actor, changes, context),
      /当前/,
    );
  assert.throws(
    () =>
      validateAccountUpdate(
        demoSession("department").user,
        account,
        { name: "未授权" },
        context,
      ),
    /管理员/,
  );
});

test("current platform account may change its name without weakening self-lock protection", () => {
  const data = fixture(),
    actor = data.accounts.find((a) => a.id === "demo-platform"),
    context = editContext(data, "platform-1");
  assert.doesNotThrow(() =>
    validateAccountUpdate(
      actor,
      actor,
      {
        name: "平台值班员",
        role: "system_admin",
        org_unit_id: null,
        is_active: true,
      },
      context,
    ),
  );
  for (const changes of [
    { is_active: false },
    { role: "school_admin" },
    { org_unit_id: "school-1" },
  ])
    assert.throws(
      () => validateAccountUpdate(actor, actor, changes, context),
      /当前/,
    );
});

test("property editing protects the last and designated school administrator", () => {
  const data = fixture(),
    actor = demoSession("platform").user,
    context = editContext(data),
    account = data.accounts.find((a) => a.id === "demo-school");
  for (const changes of [
    { is_active: false },
    { role: "department_admin", org_unit_id: "dept-10" },
  ])
    assert.throws(
      () => validateAccountUpdate(actor, account, changes, context),
      /最后一位/,
    );
  const otherAdmin = { ...account, id: "other-admin" };
  const withReplacement = {
    ...context,
    tenant: { ...context.tenant, school_admin_user_id: undefined },
    accounts: [...context.accounts, otherAdmin],
  };
  assert.doesNotThrow(() =>
    validateAccountUpdate(
      actor,
      account,
      { is_active: false },
      withReplacement,
    ),
  );
  assert.throws(
    () =>
      validateAccountUpdate(
        actor,
        account,
        { is_active: false },
        {
          ...withReplacement,
          tenant: { ...context.tenant, school_admin_user_id: account.id },
        },
      ),
    /主要管理员/,
  );
  assert.throws(
    () =>
      validateAccountUpdate(
        actor,
        account,
        { is_active: false },
        {
          ...context,
          accounts: [
            ...context.accounts,
            { ...otherAdmin, tenant_id: "school-2" },
          ],
        },
      ),
    /最后一位/,
  );
});

test("editing retains login identity and forbids drifting a linked personal account to another branch", () => {
  const data = fixture(),
    actor = demoSession("platform").user,
    context = editContext(data),
    account = data.accounts.find((a) => a.id === "demo-student");
  assert.throws(
    () =>
      validateAccountUpdate(
        actor,
        account,
        { username: "changed-login" },
        context,
      ),
    /身份标识/,
  );
  assert.throws(
    () =>
      validateAccountUpdate(actor, account, { tenant_id: "school-2" }, context),
    /所属租户/,
  );
  assert.throws(
    () =>
      validateAccountUpdate(
        actor,
        account,
        { role: "member", org_unit_id: "test-branch" },
        context,
      ),
    /本人档案/,
  );
  assert.throws(
    () => validateAccountUpdate(actor, account, { name: "   " }, context),
    /姓名/,
  );
  assert.throws(
    () =>
      validateAccountUpdate(actor, account, { is_active: "false" }, context),
    /账号状态/,
  );
  assert.throws(
    () =>
      validateAccountUpdate(
        actor,
        account,
        { name: "修改" },
        { ...context, tenant: { ...context.tenant, is_active: false } },
      ),
    /学校已停用/,
  );
});
test("platform has exactly the six requested primary entries and keeps party business in school roles", () => {
  assert.deepEqual(
    PLATFORM_NAV_SPEC.map((n) => n.label),
    [
      "平台工作台",
      "租户管理",
      "账号与权限",
      "系统运维",
      "平台配置",
      "安全审计",
    ],
  );
  for (const item of PLATFORM_NAV_SPEC)
    assert.equal(canAccess(demoSession("platform"), item), true);
  for (const id of [
    "members",
    "assistant",
    "reviews",
    "knowledge",
    "settings",
    "learning",
  ])
    assert.equal(canAccess(demoSession("platform"), { id }), false);
  assert.ok(PLATFORM_ROUTES.has("profile"));
  assert.equal(
    canAccess(demoSession("school"), {
      id: "operations",
      roles: ["system_admin"],
    }),
    false,
  );
});
test("platform migration preserves changes and is idempotent even without a version marker", () => {
  const first = fixture();
  first.platform.config.auth.session_minutes = 45;
  first.tenants.find((t) => t.id === "school-2").name = "已修改学校";
  delete first.platform.version;
  const next = extendPlatformData(first),
    again = extendPlatformData(next);
  assert.equal(next.tenants.length, 4);
  assert.equal(next.accounts.length, 10);
  assert.equal(next.auditEntries.length, first.auditEntries.length);
  assert.equal(
    again.tenants.find((t) => t.id === "school-2").name,
    "已修改学校",
  );
  assert.equal(again.platform.config.auth.session_minutes, 45);
  const partial = extendPlatformData({
    ...next,
    platform: { version: 1, config: { auth: { session_minutes: 60 } } },
  });
  assert.equal(partial.platform.config.auth.session_minutes, 60);
  assert.equal(partial.platform.config.auth.password_login, true);
});
test("new school administrators never inherit other school rosters, meetings or organizations", () => {
  const data = fixture(),
    school2 = sessionForAccount(
      data.accounts.find((a) => a.id === "demo-school-2-admin"),
    );
  assert.equal(scopedMembers(data, school2).length, 0);
  assert.equal(scopedMeetings(data, school2).length, 0);
  assert.equal(scopedOrganizations(school2).length, 0);
  assert.equal(scopedMembers(data, demoSession("school")).length, 1286);
  const crossTenant = { ...data.meetings[0], tenant_id: "school-2" };
  assert.equal(
    scopedMeetings({ meetings: [crossTenant] }, demoSession("school")).length,
    0,
  );
});
test("disabled accounts cannot resume through persona fallback and inactive tenants block login", () => {
  const data = fixture(),
    student = data.accounts.find((a) => a.id === "demo-student"),
    school3 = data.accounts.find((a) => a.id === "demo-school-3-admin");
  student.is_active = false;
  assert.equal(demoAccountAvailable(student, data.tenants), false);
  assert.equal(
    normalizeDemoSession(demoSession("student"), data.accounts, data.tenants),
    null,
  );
  assert.equal(demoAccountAvailable(school3, data.tenants), false);
  assert.equal(
    normalizeDemoSession(
      sessionForAccount(school3),
      data.accounts,
      data.tenants,
    ),
    null,
  );
  assert.ok(
    normalizeDemoSession(demoSession("platform"), data.accounts, data.tenants),
  );
});
test("platform overview counters respond to processed incidents and task state", () => {
  const data = fixture(),
    before = platformSummary(data);
  assert.equal(before.schools, 3);
  assert.equal(before.activeSchools, 2);
  assert.equal(before.failedJobs, 2);
  data.platform.jobs[0].status = "completed";
  data.platform.incidents[0].status = "resolved";
  const after = platformSummary(data);
  assert.equal(after.failedJobs, 1);
  assert.equal(after.incidents, before.incidents - 1);
});
test("school admin association and current administrator safeguards reject wrong identities", () => {
  const actor = { id: "root", role: "system_admin" },
    school = {
      id: "school-admin",
      tenant_id: "school-2",
      role: "school_admin",
      is_active: true,
    };
  assert.equal(validSchoolAdmin(school, "school-2"), true);
  assert.equal(validSchoolAdmin(school, "school-1"), false);
  assert.equal(
    validSchoolAdmin({ ...school, is_active: false }, "school-2"),
    false,
  );
  assert.throws(
    () => validateAdminChange(actor, actor, { is_active: false }),
    /不能停用/,
  );
  assert.throws(
    () => validateAdminChange(actor, actor, { role: "school_admin" }),
    /当前/,
  );
  assert.throws(
    () => validateAdminChange(school, actor, { is_active: false }),
    /本校/,
  );
});
test("platform settings reject lockout, unsupported formats and credentials embedded in service URLs", () => {
  assert.match(
    validatePlatformConfig("auth", {
      password_login: false,
      sso_enabled: false,
    }),
    /至少/,
  );
  assert.match(
    validatePlatformConfig("uploads", {
      max_file_mb: 20,
      allowed_extensions: ["exe"],
      retention_days: 365,
    }),
    /文件格式/,
  );
  assert.match(
    validatePlatformConfig("model", {
      model_name: "qwen",
      base_url: "https://example.com/?api_key=secret",
      timeout_seconds: 60,
    }),
    /地址/,
  );
  assert.equal(
    validatePlatformConfig("uploads", {
      max_file_mb: 5,
      allowed_extensions: ["pdf"],
      retention_days: 365,
    }),
    "",
  );
});
test("saved upload policy restricts personal file formats and size, without broadening backend types", () => {
  assert.throws(
    () => validateMaterialFile({ name: "学习.txt", size: 20 }, 1024, ["pdf"]),
    /未允许/,
  );
  assert.doesNotThrow(() =>
    validateMaterialFile({ name: "申请.pdf", size: 1000 }, 1024, ["pdf"]),
  );
  assert.throws(
    () => validateMaterialFile({ name: "申请.exe", size: 100 }, 1024, ["exe"]),
    /支持 PDF/,
  );
});
