import { hasPermission, memberInScope, recordInScope } from "./roles.js";
import { STAGES } from "./data.js";
export function submitDemoMeeting(session, current, expectedRevision, reason) {
  if (
    !current ||
    !hasPermission(session, "meeting.manage") ||
    !recordInScope(session.user, current)
  )
    throw new Error("该记录不在当前账号的办理范围内。");
  if (
    current.revision !== expectedRevision ||
    !["待召开", "已退回"].includes(current.status)
  )
    throw new Error("会议版本或状态已变化，请重新核对。");
  if (!current.minutes?.trim()) throw new Error("请先编辑并保存会议纪要。");
  if (!reason.trim()) throw new Error("请填写提交说明。");
  return {
    ...current,
    status: "待审核",
    review_status: "pending",
    submitted_by: session.user.id,
    submitted_name: session.user.name,
    submission_reason: reason.trim(),
    review_opinion: null,
    revision: current.revision + 1,
  };
}
export function reviewDemoMeeting(
  session,
  current,
  expectedRevision,
  decision,
  reason,
) {
  if (!current) throw new Error("记录已不存在，请刷新后重新核对。");
  if (
    !hasPermission(session, "meeting.review") ||
    !recordInScope(session.user, current)
  )
    throw new Error("该记录不在当前账号的审核范围内。");
  if (current.submitted_by === session.user.id)
    throw new Error(
      "提交人不能审核自己的会议纪要，请由另一位授权组织人员审核。",
    );
  if (current.revision !== expectedRevision || current.status !== "待审核")
    throw new Error("记录已发生变化，请刷新后重新核对。");
  if (!reason.trim()) throw new Error("请填写审核意见。");
  if (!["approved", "rejected"].includes(decision))
    throw new Error("审核决定无效。");
  return {
    ...current,
    status: decision === "approved" ? "已完成" : "已退回",
    review_status: decision,
    reviewed_by: session.user.id,
    review_opinion: reason.trim(),
    revision: current.revision + 1,
  };
}
export function transitionDemoMember(
  session,
  member,
  target,
  basis,
  opinion,
  decisionDate = new Date().toISOString().slice(0, 10),
) {
  if (
    !hasPermission(session, "member.stage_transition") ||
    !memberInScope(session.user, member)
  )
    throw new Error("该档案不在当前账号的办理范围内。");
  if (STAGES.indexOf(target) !== STAGES.indexOf(member.stage) + 1)
    throw new Error("请按相邻阶段办理，不支持跳过或倒退发展阶段。");
  if (!basis.trim() || !opinion.trim())
    throw new Error("请填写人工办理依据和意见。");
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(decisionDate) ||
    decisionDate > new Date().toISOString().slice(0, 10)
  )
    throw new Error("请填写有效且不晚于今天的决定日期。");
  return {
    ...member,
    stage: target,
    joined: decisionDate,
    stage_joined_on: decisionDate,
  };
}
export function linkDemoAccount(session, member, accounts, username) {
  if (
    !hasPermission(session, "member.stage_transition") ||
    !memberInScope(session.user, member)
  )
    throw new Error("该档案不在当前账号的关联范围。");
  const account = accounts.find(
    (a) =>
      a.username === username &&
      a.is_active &&
      ["member", "applicant"].includes(a.role) &&
      a.org_unit_id === member.orgId &&
      a.tenant_id === session.user.tenant_id,
  );
  if (!account) throw new Error("请选择同一组织内有效的党员或申请人账号。");
  if (accounts.some((a) => a.profile_id === member.id && a.id !== account.id))
    throw new Error("此档案已关联其他账号，请先由组织核实。");
  if (account.profile_id && account.profile_id !== member.id)
    throw new Error("该账号已关联其他档案，不能重复关联。");
  return accounts.map((a) =>
    a.id === account.id ? { ...a, profile_id: member.id } : a,
  );
}
