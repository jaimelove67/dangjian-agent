import { useCallback, useRef } from "react";
import { IS_LIVE } from "./api";
import { get, send } from "./business-api";
import { useApp } from "./app-context";
import { useStore } from "./store";
import { newAudit } from "./role-data";
import { mutateLocalEducation, readLocalEducation } from "./education-local.js";

export function useEducationApi() {
  const { session } = useApp(), { data, update } = useStore();
  const identity = `${session.user.tenant_id}:${session.user.id}:${session.user.role}:${session.user.org_unit_id}`;
  const current = useRef({ data, user: session.user, identity });
  current.current = { data, user: session.user, identity };
  const read = useCallback(async (path, query) => {
    if (current.current.identity !== identity) throw new Error("账号已变更，请重新进入学习页面。");
    return IS_LIVE ? get(path, query) : readLocalEducation(current.current.data, current.current.user, path, query);
  }, [identity]);
  const write = useCallback(async (path, body = {}) => {
    if (current.current.identity !== identity) throw new Error("账号已变更，请重新进入学习页面。");
    if (IS_LIVE) return send(path, body);
    const { state, value, action, resourceId } = mutateLocalEducation(current.current.data, current.current.user, path, body);
    current.current.data = { ...current.current.data, education: state };
    update("education", state);
    if (!path.endsWith("/heartbeat")) update("auditEntries", (previous = []) => [newAudit(current.current.user, ({ publish: "发布学习内容", enroll: "开始学习或报名", exam: "提交学习测评", attendance: "核验活动出席", cancel: "取消本人报名", notes: "保存本人学习笔记" })[action] || action, "education", resourceId), ...previous]);
    return value;
  }, [identity, update]);
  return { get: read, send: write, identity, revision: IS_LIVE ? 0 : data.education?.revision || 0 };
}
