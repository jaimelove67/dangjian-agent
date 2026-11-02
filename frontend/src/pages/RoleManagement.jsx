import { useEffect, useState } from "react";
import {
  FileText,
  DownloadSimple,
  CheckCircle,
  ClipboardText,
  UserCircle,
  Plus,
  ArrowRight,
  IdentificationCard,
  Clock,
  ShieldCheck,
  ArrowsClockwise,
  WarningCircle,
} from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE, backend, getSession } from "../api";
import { roleApi } from "../role-api";
import { MaterialSuggestions, useMaterialDraft } from "../components/MaterialSuggestions";
import { validateMaterialFile } from "../material-validation";
import { useManagedWorkspace } from "../role-hooks";
import { scopedMeetings, hasPermission, memberInScope } from "../roles";
import {
  MATERIAL_CATEGORIES,
  materialSource,
  materialSourceNote,
  materialTypeLabel,
  newAudit,
  getDemoDevelopment,
  emptyProcedureState,
  addDemoProcedure,
  buildDemoFlowBoard,
} from "../role-data";
import { getDemoFile } from "../demo-files";
import {
  reviewDemoMeeting,
  transitionDemoMember,
  linkDemoAccount,
} from "../role-actions";
import { STAGES } from "../data";
import { STAGE_LABELS } from "../contracts";
import { leagueEligibility, todayIso } from "../league-eligibility";
import {
  PageHeader,
  PanelTitle,
  Tabs,
  SearchInput,
  Select,
  Badge,
  Empty,
  Loading,
  ErrorBox,
  Modal,
  Field,
  Pagination,
  downloadBlob,
} from "../components";

export function MaterialInbox() {
  const { session, routeParams } = useApp();
  const { data, update, notify } = useStore();
  const w = useManagedWorkspace();
  const [selected, setSelected] = useState(routeParams.profileId || "");
  const [query, setQuery] = useState("");
  const [items, setItems] = useState([]);
  const [loadedKey, setLoadedKey] = useState("");
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!selected && w.members.length) setSelected(w.members[0].id);
  }, [w.members.length, selected]);
  useEffect(() => {
    if (!IS_LIVE || !selected) return;
    let active = true;
    setItems([]);
    setTotal(0);
    setDetail(null);
    setLoadedKey("");
    setLoading(true);
    setError(null);
    roleApi
      .receivedMaterials(selected, page)
      .then((res) => {
        if (active) {
          setItems(
            (res.items || []).map((m) => ({
              ...m,
              profile_id: m.profile_id || selected,
            })),
          );
          setTotal(res.total || 0);
          setLoadedKey(`${selected}:${page}`);
        }
      })
      .catch((e) => {
        if (active) setError(e);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [selected, page, session.user.id]);
  const ids = new Set(w.members.map((m) => m.id));
  const all = IS_LIVE
    ? loadedKey === `${selected}:${page}`
      ? items
      : []
    : data.personalMaterials.filter((m) => ids.has(m.profile_id));
  const filtered = all.filter(
    (m) =>
      (!IS_LIVE || m.profile_id === undefined || m.profile_id === selected) &&
      (!query ||
        `${m.title} ${w.members.find((p) => p.id === m.profile_id)?.name || ""}`.includes(
          query,
        )),
  );
  function view(m) {
    setDetail(m);
    if (
      !IS_LIVE &&
      !data.materialReceipts.some(
        (r) => r.material_id === m.id && r.viewer_id === session.user.id,
      )
    )
      update("materialReceipts", (prev) => [
        ...prev,
        {
          material_id: m.id,
          viewer_id: session.user.id,
          viewed_at: new Date().toISOString(),
        },
      ]);
  }
  async function download(m) {
    try {
      if (!hasPermission(session, "member.query"))
        throw new Error("当前账号没有接收材料的权限。");
      const profile = m.profile_id;
      if (
        IS_LIVE &&
        (profile !== selected || loadedKey !== `${selected}:${page}`)
      )
        throw new Error("材料列表已变化，请重新选择后下载。");
      if (!w.members.some((p) => p.id === profile))
        throw new Error("该材料不在当前组织范围。");
      const blob = IS_LIVE
        ? await roleApi.receivedFile(profile, m.id)
        : await getDemoFile(m.id, m.owner_id);
      if (getSession()?.user?.id === session.user.id)
        downloadBlob(blob, m.file_name);
    } catch (e) {
      notify(e.message, "error");
    }
  }
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title="材料接收"
        subtitle="按授权组织接收个人材料，核对原件与提交说明"
      />
      <div className="table-toolbar">
        <SearchInput
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索材料标题或提交人"
        />
        {IS_LIVE && (
          <Select
            label="选择提交人"
            value={selected}
            onChange={(e) => {
              setSelected(e.target.value);
              setPage(1);
            }}
          >
            {w.members.map((p) => (
              <option value={p.id} key={p.id}>
                {p.name} · {p.organization}
              </option>
            ))}
          </Select>
        )}
        <span className="toolbar-spacer" />
        <Badge tone="blue">组织授权接收</Badge>
      </div>
      {(error || w.error) && (
        <ErrorBox error={error || w.error} retry={w.reload} />
      )}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>材料名称</th>
              <th>提交人</th>
              <th>所属组织</th>
              <th>提交时间</th>
              <th>接收记录</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((m) => (
              <tr key={m.id}>
                <td>
                  <button className="file-name" onClick={() => view(m)}>
                    <FileText size={22} />
                    {m.title}
                  </button>
                  <small className="cell-subtext">
                    {MATERIAL_CATEGORIES[m.category]}
                  </small>
                </td>
                <td>
                  {w.members.find((p) => p.id === (m.profile_id || selected))
                    ?.name || "—"}
                </td>
                <td>
                  {w.members.find((p) => p.id === (m.profile_id || selected))
                    ?.organization || "—"}
                </td>
                <td>{m.created_at.slice(0, 10)}</td>
                <td>
                  <Badge
                    tone={
                      data.materialReceipts.some(
                        (r) =>
                          r.material_id === m.id &&
                          r.viewer_id === session.user.id,
                      )
                        ? "green"
                        : "blue"
                    }
                  >
                    {data.materialReceipts.some(
                      (r) =>
                        r.material_id === m.id &&
                        r.viewer_id === session.user.id,
                    )
                      ? "已查阅"
                      : "已提交"}
                  </Badge>
                </td>
                <td>
                  <button className="text-button link" onClick={() => view(m)}>
                    查阅
                  </button>
                  <button
                    className="text-button link separated-action"
                    disabled={!IS_LIVE && !m.has_file}
                    onClick={() => download(m)}
                  >
                    下载原件
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(loading || w.loading) && <Loading />}
        {!filtered.length && !loading && !w.loading && (
          <Empty
            title="暂无已提交材料"
            description="仅接收已明确关联档案且处于授权组织范围内的个人材料。"
          />
        )}
      </div>
      {IS_LIVE && total > 20 && (
        <div className="table-footer">
          <Pagination
            page={page}
            pages={Math.ceil(total / 20)}
            total={total}
            onChange={setPage}
          />
        </div>
      )}
      <div className="page-note">
        查阅状态仅表示当前账号已打开材料。材料核验、归档和党员发展决定须按相应业务流程办理。
      </div>
      {detail && (
        <Modal title="查阅个人材料" wide flat onClose={() => setDetail(null)}>
          <div className="document-heading">
            <FileText size={35} />
            <div>
              <h3>{detail.title}</h3>
              <p>
                {detail.file_name} · {detail.created_at.slice(0, 10)}
              </p>
            </div>
          </div>
          <p className="body-copy">{detail.description || "无补充说明"}</p>
          <div className="inline-note">
            个人原件仅按授权下载，不自动发送给模型，不自动进入知识库。
          </div>
          <div className="modal-actions">
            <button
              className="button secondary"
              disabled={!IS_LIVE && !detail.has_file}
              onClick={() => download(detail)}
            >
              <DownloadSimple size={17} />
              下载原件
            </button>
            <button className="button primary" onClick={() => setDetail(null)}>
              完成查阅
            </button>
          </div>
        </Modal>
      )}
    </section>
  );
}
export function ReviewCenter() {
  const { session, navigate } = useApp();
  const { data, update, notify } = useStore();
  const [tab, setTab] = useState("待审核");
  const [query, setQuery] = useState("");
  const [records, setRecords] = useState([]);
  const [generic, setGeneric] = useState([]);
  const [detail, setDetail] = useState(null);
  const [decision, setDecision] = useState("approved");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!IS_LIVE) return;
    let active = true;
    setBusy(true);
    Promise.all([
      hasPermission(session, "meeting.query")
        ? backend.meetings()
        : { items: [] },
      roleApi.reviews(),
    ])
      .then(([meetings, reviews]) => {
        if (active) {
          setRecords(
            (meetings.items || [])
              .filter(
                (m) =>
                  m.submitted_by ||
                  ["pending", "approved", "rejected"].includes(m.review_status),
              )
              .map((m) => ({
                ...m,
                title: m.title,
                date: m.scheduled_on,
                status:
                  m.review_status === "pending"
                    ? "待审核"
                    : m.review_status === "approved"
                      ? "已完成"
                      : "已退回",
                orgId: m.org_unit_id,
                organization: m.org_unit_id,
                minutes: m.transcript,
                review_kind: "meeting",
              })),
          );
          setGeneric(reviews.items || []);
        }
      })
      .catch((e) => {
        if (active) setError(e);
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [tick, session.user.id]);
  const meetings = IS_LIVE
    ? records
    : scopedMeetings(data, session).filter(
        (m) => m.submitted_by || m.status === "待审核",
      );
  const rows = meetings.filter(
    (m) =>
      m.title.includes(query) &&
      (tab === "待审核" ? m.status === "待审核" : m.status !== "待审核"),
  );
  async function open(m, kind = "meeting") {
    setError(null);
    setDecision("approved");
    if (kind === "generic") {
      setBusy(true);
      try {
        setDetail({
          ...(await roleApi.reviewDetail(m.id)),
          review_kind: "generic",
        });
      } catch (e) {
        setError(e);
      } finally {
        setBusy(false);
      }
    } else setDetail({ ...m, review_kind: "meeting" });
  }
  async function review(e) {
    e.preventDefault();
    const reason = new FormData(e.currentTarget).get("opinion").trim();
    setBusy(true);
    setError(null);
    try {
      if (!hasPermission(session, "admin.review"))
        throw new Error("当前账号没有审核权限。");
      if (detail.submitted_by === session.user.id)
        throw new Error("提交人不能审核自己的记录。");
      if (!reason) throw new Error("请填写审核意见。");
      if (IS_LIVE) {
        if (detail.review_kind === "generic") {
          await roleApi.decideReview(detail.id, {
            decision: decision === "approved" ? "approved" : "returned",
            source_version: detail.source_version,
            opinion: reason,
          });
        } else {
          await roleApi.meetingAction(
            detail.id,
            "review",
            detail.revision,
            reason,
            decision,
          );
        }
        setTick((t) => t + 1);
      } else {
        const current = data.meetings.find((m) => m.id === detail.id);
        const result = reviewDemoMeeting(
          session,
          current,
          detail.revision,
          decision,
          reason,
        );
        update("meetings", (prev) =>
          prev.map((m) => (m.id === result.id ? result : m)),
        );
        update("auditEntries", (prev) => [
          newAudit(
            session.user,
            decision === "approved" ? "审核通过会议纪要" : "退回会议纪要",
            "meeting",
            detail.id,
          ),
          ...prev,
        ]);
      }
      setDetail(null);
      notify(
        decision === "approved" ? "人工审核已登记" : "已退回，请提交人补充完善",
      );
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title="审核工作台"
        subtitle="逐项核对来源与版本，由授权人员独立作出决定"
      />
      <Tabs
        items={["待审核", "已处理", ...(IS_LIVE ? ["综合审核"] : [])]}
        active={tab}
        onChange={setTab}
      />
      <div className="table-toolbar">
        <SearchInput
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索审核事项"
        />
        <span className="toolbar-spacer" />
        <span className="small-text muted">提交人和审核人分开办理</span>
      </div>
      {error && !detail && (
        <ErrorBox error={error} retry={() => setTick((t) => t + 1)} />
      )}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>审核事项</th>
              <th>业务类型</th>
              <th>所属组织 / 来源</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {tab === "综合审核"
              ? generic
                  .filter((r) =>
                    `${r.source_kind} ${r.source_id}`.includes(query),
                  )
                  .map((r) => (
                    <tr key={r.id}>
                      <td>
                        {{
                          score: "辅助评分",
                          vote: "投票汇总",
                          member_review: "民主评议",
                          study_activity: "学习纪要",
                          study_plan: "学习计划",
                          assessment_report: "考核报告",
                          assessment_plan: "年度计划",
                          meeting: "组织生活",
                        }[r.source_kind] || "业务审核"}
                      </td>
                      <td>{r.source_id}</td>
                      <td>{r.created_at?.slice(0, 10)}</td>
                      <td>
                        <Badge tone={r.stale ? "red" : "orange"}>
                          {r.stale ? "来源已变更" : "待审核"}
                        </Badge>
                      </td>
                      <td>
                        <button
                          className="text-button link"
                          onClick={() => open(r, "generic")}
                        >
                          核对并审核
                        </button>
                      </td>
                    </tr>
                  ))
              : rows.map((m) => (
                  <tr key={m.id}>
                    <td>
                      {m.title}
                      <small className="cell-subtext">{m.date}</small>
                    </td>
                    <td>组织生活纪要</td>
                    <td>{m.organization}</td>
                    <td>
                      <Badge
                        tone={
                          m.status === "待审核"
                            ? "orange"
                            : m.status === "已完成"
                              ? "green"
                              : "red"
                        }
                      >
                        {m.status}
                      </Badge>
                    </td>
                    <td>
                      <button
                        className="text-button link"
                        onClick={() => open(m)}
                      >
                        {m.status === "待审核" ? "核对并审核" : "查看记录"}
                      </button>
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>
        {busy && !detail && <Loading />}
        {!(tab === "综合审核" ? generic.length : rows.length) && !busy && (
          <Empty
            title="暂无此类审核事项"
            description="已提交的记录会按当前组织授权范围进入待办。"
          />
        )}
      </div>
      <div className="page-note">
        审核结果保留意见与版本。纪要审核通过后，电子归档仍须满足学校确认的归档政策。
      </div>
      {detail && (
        <Modal title="核对并审核" wide flat onClose={() => !busy && setDetail(null)}>
          <h3 className="review-title">{detail.title || "综合业务审核"}</h3>
          <div className="detail-meta">
            <Badge tone="orange">{detail.status}</Badge>
            <span>
              提交人：
              {detail.submitted_name ||
                data.accounts.find((a) => a.id === detail.submitted_by)?.name ||
                detail.submitted_by}
            </span>
            <span>
              当前版本：
              {detail.revision || detail.source_version?.slice(0, 10) || "—"}
            </span>
          </div>
          {detail.minutes ? (
            <div className="review-transcript">{detail.minutes}</div>
          ) : (
            <div className="inline-note">
              请先核对原始业务记录及其佐证：{detail.source_kind} /{" "}
              {detail.source_id}。
            </div>
          )}
          {detail.review_opinion && (
            <p className="body-copy">处理意见：{detail.review_opinion}</p>
          )}
          {detail.stale && (
            <ErrorBox
              error={
                new Error("来源记录已变更，请重新提交审核，当前版本不能通过。")
              }
            />
          )}{" "}
          {detail.submitted_by === session.user.id && (
            <div className="inline-note">
              这是由当前账号提交的记录，请切换另一位同范围授权组织人员审核。
            </div>
          )}
          {(detail.status === "待审核" || detail.review_kind === "generic") && (
            <form onSubmit={review}>
              <div className="review-decision">
                <label>
                  <input
                    type="radio"
                    name="decision"
                    checked={decision === "approved"}
                    onChange={() => setDecision("approved")}
                  />
                  审核通过
                </label>
                <label>
                  <input
                    type="radio"
                    name="decision"
                    checked={decision === "rejected"}
                    onChange={() => setDecision("rejected")}
                  />
                  退回补充
                </label>
              </div>
              <Field label="审核意见" required>
                <textarea
                  name="opinion"
                  required
                  rows={3}
                  maxLength={2000}
                  placeholder="请写明核对依据及处理意见"
                />
              </Field>
              {error && <ErrorBox error={error} />}
              <div className="modal-actions">
                <button
                  className="button secondary"
                  type="button"
                  disabled={busy}
                  onClick={() => setDetail(null)}
                >
                  取消
                </button>
                <button
                  className="button primary"
                  disabled={
                    busy ||
                    detail.submitted_by === session.user.id ||
                    detail.stale
                  }
                >
                  {busy ? "提交中…" : "提交审核决定"}
                </button>
              </div>
            </form>
          )}
        </Modal>
      )}
    </section>
  );
}
const DEVELOPMENT_TABS = [
  "材料清单",
  "培养记录",
  "发展程序",
  "阶段流转",
  "流程看板",
];
const DEVELOPMENT_STEP_GROUPS = [
  "入党申请人",
  "入党积极分子",
  "发展对象",
  "预备党员",
  "正式党员",
];
const DEVELOPMENT_STEPS = [
  { no: 1, title: "递交入党申请书", group: 0, check: "application" },
  { no: 2, title: "党组织派人谈话", group: 0, check: "talk" },
  { no: 3, title: "确定入党积极分子", group: 0 },
  { no: 4, title: "上级党委备案", group: 1, check: "upper" },
  { no: 5, title: "指定培养联系人", group: 1, check: "contact" },
  { no: 6, title: "培养教育考察", group: 1, check: "cultivation" },
  { no: 7, title: "确定发展对象", group: 1 },
  { no: 8, title: "上级党委备案", group: 2, check: "upper" },
  { no: 9, title: "确定入党介绍人", group: 2, check: "introducer" },
  { no: 10, title: "进行政治审查", group: 2, check: "political" },
  { no: 11, title: "短期集中培训", group: 2, check: "training" },
  { no: 12, title: "支委会审查", group: 2, check: "branch_review" },
  { no: 13, title: "上级党委预审", group: 2, check: "upper_pre_review" },
  { no: 14, title: "填写入党志愿书", group: 2, check: "application_form" },
  { no: 15, title: "支部大会讨论", group: 2, check: "reception_vote" },
  { no: 16, title: "上级党委派人谈话", group: 3, check: "upper_talk" },
  { no: 17, title: "上级党委审批", group: 3, check: "upper" },
  { no: 18, title: "再上一级党委组织部门备案", group: 3, check: "higher_record" },
  { no: 19, title: "编入党支部和党小组", group: 3, check: "party_group" },
  { no: 20, title: "入党宣誓", group: 3, check: "oath" },
  { no: 21, title: "继续教育考察", group: 4, check: "continued" },
  { no: 22, title: "提出转正申请", group: 4, check: "transfer_application" },
  { no: 23, title: "支部大会讨论转正", group: 4, check: "conversion" },
  { no: 24, title: "上级党委审批", group: 4, check: "upper" },
  { no: 25, title: "材料归档", group: 4, check: "archive" },
];
function addCalendarMonths(value, months) {
  if (!value) return null;
  const [year, month, day] = String(value).slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) return null;
  const target = new Date(year, month - 1 + months, 1);
  const last = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
  target.setDate(Math.min(day, last));
  const pad = (value) => String(value).padStart(2, "0");
  return `${target.getFullYear()}-${pad(target.getMonth() + 1)}-${pad(target.getDate())}`;
}
function dateOnly(value) {
  return value ? String(value).slice(0, 10) : "";
}
function addCalendarDays(value, days) {
  const text = dateOnly(value);
  if (!text) return null;
  const [year, month, day] = text.split("-").map(Number);
  if (!year || !month || !day) return null;
  const target = new Date(year, month - 1, day + days);
  const pad = (item) => String(item).padStart(2, "0");
  return `${target.getFullYear()}-${pad(target.getMonth() + 1)}-${pad(target.getDate())}`;
}
function daysUntil(value) {
  const text = dateOnly(value);
  if (!text) return null;
  const [year, month, day] = text.split("-").map(Number);
  if (!year || !month || !day) return null;
  const now = new Date();
  const target = Date.UTC(year, month - 1, day);
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.ceil((target - today) / 86400000);
}
function DevelopmentWizard({
  stage,
  stageJoinedOn,
  earliest,
  remainingDays,
  nextAction,
  steps,
  shortcuts,
  onShortcut,
}) {
  const stageIndex = Math.max(0, DEVELOPMENT_STEP_GROUPS.indexOf(stage));
  return (
    <div className="development-wizard">
      <div className="development-wizard-summary">
        <div>
          <span>当前阶段</span>
          <strong>{stage || "未登记"}</strong>
        </div>
        <div>
          <span>进入阶段</span>
          <strong>{stageJoinedOn || "未登记"}</strong>
        </div>
        <div>
          <span>下一办理</span>
          <strong>{nextAction || "按组织程序办理"}</strong>
        </div>
        <div>
          <span>最早可办理</span>
          <strong>
            {earliest
              ? remainingDays > 0
                ? `${earliest}（还需 ${remainingDays} 天）`
                : `${earliest}（已满足）`
              : "无固定间隔"}
          </strong>
        </div>
      </div>
      {shortcuts.length > 0 && (
        <div className="development-wizard-shortcuts">
          <span>当前缺项</span>
          {shortcuts.map((shortcut) => (
            <button
              type="button"
              className="button secondary"
              key={shortcut.label}
              onClick={() => onShortcut(shortcut)}
            >
              {shortcut.label}
              <ArrowRight size={13} />
            </button>
          ))}
        </div>
      )}
      <div className="development-step-groups">
        {DEVELOPMENT_STEP_GROUPS.map((group, groupIndex) => {
          const groupSteps = steps.filter((step) => step.group === groupIndex);
          const done = groupSteps.filter((step) => step.state === "done").length;
          return (
            <details
              className="development-step-group"
              key={group}
              open={groupIndex === stageIndex}
            >
              <summary>
                <span>{group}</span>
                <small>
                  {done}/{groupSteps.length} 已具备
                </small>
              </summary>
              <ol>
                {groupSteps.map((step) => (
                  <li key={step.no} className={`step-${step.state}`}>
                    <span className="development-step-no">{step.no}</span>
                    <span>{step.title}</span>
                    <small>
                      {
                        {
                          done: "已完成",
                          current: "待办理",
                          pending: "未开始",
                          check: "请核对",
                        }[step.state]
                      }
                    </small>
                  </li>
                ))}
              </ol>
            </details>
          );
        })}
      </div>
    </div>
  );
}

const VOTE_MEETING_LABELS = {
  reception: "接收预备党员",
  conversion: "预备党员转正",
  disqualification: "取消预备党员资格",
};
const REMINDER_LABELS = {
  higher_record: "再上一级党委组织部门备案",
  party_group: "编入党支部和党小组",
  oath: "入党宣誓",
  probationary_expiration: "预备期届满",
  probationary_expiration_advance: "预备期即将届满",
  material_submission: "材料提交",
  material_submission_advance: "材料提交临近",
  training_period: "培养期",
  training_period_advance: "培养期临近",
  meeting_discussion: "会议讨论",
  meeting_discussion_advance: "会议讨论临近",
};
function FlowBoard({ board, loading, error, canResolve, onSelect, onResolve, onRefresh }) {
  const summary = board?.stage_summary || [];
  const visibleStages = summary.filter(
    (stage) =>
      stage.count > 0 ||
      ["applicant", "activist", "candidate", "probationary", "member"].includes(
        stage.stage,
      ),
  );
  return (
    <div className="flow-board-wrap">
      <div className="sub-toolbar">
        <span>
          {board?.notice ||
            "按阶段汇总材料、程序事实和提醒；点击人员进入具体办理。"}
        </span>
        <button
          type="button"
          className="button secondary"
          disabled={loading}
          onClick={onRefresh}
        >
          <ArrowsClockwise size={15} />
          刷新看板
        </button>
      </div>
      {error && <ErrorBox error={error} retry={onRefresh} />}
      {loading && !board && <Loading />}
      {board && (
        <>
          <div className="flow-summary">
            {visibleStages.map((stage) => (
              <span key={stage.stage}>
                {stage.label}
                <strong>{stage.count}</strong>
              </span>
            ))}
          </div>
          <div className="flow-board">
            {visibleStages.map((stage) => {
              const items = (board.items || []).filter(
                (item) => item.current_stage === stage.stage,
              );
              return (
                <section className="flow-column" key={stage.stage}>
                  <header>
                    <h3>{stage.label}</h3>
                    <Badge
                      tone={
                        ["disqualified", "rejected"].includes(stage.stage)
                          ? "red"
                          : "blue"
                      }
                    >
                      {items.length}
                    </Badge>
                  </header>
                  <div className="flow-column-list">
                    {items.map((item) => (
                      <article className="flow-card" key={item.id}>
                        <button
                          type="button"
                          className="flow-card-title"
                          onClick={() => onSelect(item.id, "材料清单")}
                        >
                          <strong>{item.name}</strong>
                          <span>{item.org_name || "未登记组织"}</span>
                        </button>
                        <div className="flow-card-meta">
                          <span>停留 {item.days_in_stage} 天</span>
                          <span>{item.next_step}</span>
                        </div>
                        {item.missing?.length > 0 && (
                          <div className="flow-gaps">
                            {item.missing.slice(0, 4).map((gap) => (
                              <span key={gap}>
                                <WarningCircle size={12} />
                                {gap}
                              </span>
                            ))}
                            {item.missing.length > 4 && (
                              <span>另有 {item.missing.length - 4} 项</span>
                            )}
                          </div>
                        )}
                        {!item.missing?.length && (
                          <div className="flow-clear">
                            <CheckCircle size={13} />
                            当前阶段未发现登记缺项
                          </div>
                        )}
                        {item.reminders?.length > 0 && (
                          <div className="flow-reminders">
                            {item.reminders.map((reminder) => (
                              <div key={reminder.id}>
                                <span>
                                  {REMINDER_LABELS[reminder.kind] || reminder.kind}
                                  <small>到期 {reminder.due_on}</small>
                                </span>
                                {reminder.kind === "oath" && canResolve ? (
                                  <button
                                    type="button"
                                    className="text-button link"
                                    onClick={() => onResolve(item, reminder)}
                                  >
                                    标记已宣誓
                                  </button>
                                ) : (
                                  <button
                                    type="button"
                                    className="text-button link"
                                    onClick={() =>
                                      onSelect(
                                        item.id,
                                        ["higher_record", "party_group"].includes(
                                          reminder.kind,
                                        )
                                          ? "发展程序"
                                          : "材料清单",
                                      )
                                    }
                                  >
                                    进入办理
                                  </button>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </article>
                    ))}
                    {!items.length && (
                      <div className="flow-empty">本阶段暂无人员</div>
                    )}
                  </div>
                </section>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
function procedureStatusLabel(group) {
  if (!group?.current) return "未登记";
  if (
    group.current.status === "assigned" &&
    group.current.kind === "party_group"
  )
    return "已编入";
  return (
    {
      assigned: "已指定",
      confirmed: "已确定",
      in_progress: "进行中",
      passed: "已通过",
      failed: "未通过",
      supplement: "待补充",
      draft: "填写中",
      submitted: "已提交",
      reviewed: "已审核",
      completed: "已完成",
      not_passed: "未通过",
      qualified: "按期转正",
      extended: "延长预备期",
      disqualified: "取消预备党员资格",
      recorded: "已备案",
    }[group.current.status] || "待核对"
  );
}
function procedureTone(group) {
  if (!group?.current) return "blue";
  if (group.current.status === "extended") return "orange";
  if (["failed", "not_passed", "disqualified"].includes(group.current.status))
    return "red";
  if (group.satisfied) return "green";
  return "orange";
}
function DevelopmentProcedurePanel({
  state,
  stage,
  canRegisterBranch,
  canRegisterUpper,
  disabled,
  onRegister,
}) {
  const contacts = state.contacts || {};
  const introducers = state.introducers || {};
  const branch = state.branch_committee_review || {};
  const preReview = state.upper_pre_review || {};
  const form = state.application_form || {};
  const talk = state.upper_talk || {};
  const branchVote = state.branch_vote || {};
  const outcome = state.probation_outcome || {};
  const higherRecord = state.higher_record || {};
  const partyGroup = state.party_group || {};
  const introducerItems = Array.isArray(introducers.current)
    ? introducers.current
    : [];
  return (
    <>
      <div className="inline-note">
        {state.requirement ||
          "接收预备党员前应完成培养联系人、入党介绍人、支委会审查、上级党委预审和入党志愿书登记；上级党委派人谈话应在上级审批前完成。系统只登记事实，不替代组织程序。"}
      </div>
      <div className="procedure-grid">
        <div className="development-gate-card">
          <span className="metric-icon blue">
            <UserCircle size={22} />
          </span>
          <div>
            <h3>
              培养联系人{" "}
              <Badge tone={contacts.satisfied ? "green" : "blue"}>
                {contacts.satisfied ? "已登记" : "未登记"}
              </Badge>
            </h3>
            <p>{contacts.notice || "尚未登记培养联系人"}</p>
            {contacts.current && (
              <p>
                {contacts.current.details?.linked_name ||
                  contacts.current.details?.external_name ||
                  "未填写姓名"}
                （
                {contacts.current.details?.linked_org ||
                  contacts.current.details?.external_org ||
                  "未填写组织"}
                ）；指定日期：{contacts.current.occurred_on || "未登记"}
                {contacts.current.details?.external
                  ? "；外部正式党员（已人工核验）"
                  : "；档案内正式党员"}
              </p>
            )}
            <p>
              培养联系人由党支部指定，优先关联本校正式党员档案；外部正式党员须人工核验并留下依据。
            </p>
          </div>
          {canRegisterBranch && (
            <button
              type="button"
              className="button secondary"
              disabled={disabled}
              onClick={() => onRegister("contact")}
            >
              {contacts.current ? "登记新联系人" : "登记培养联系人"}
            </button>
          )}
        </div>

        <div className="development-gate-card">
          <span className="metric-icon blue">
            <IdentificationCard size={22} />
          </span>
          <div>
            <h3>
              入党介绍人{" "}
              <Badge tone={introducers.satisfied ? "green" : "blue"}>
                {introducers.count
                  ? `已登记 ${introducers.count} 名`
                  : "未登记"}
              </Badge>
            </h3>
            <p>{introducers.notice || "尚未登记入党介绍人"}</p>
            {introducerItems.map((item) => (
              <p key={item.id}>
                {item.title || "入党介绍人"}：
                {item.details?.linked_name ||
                  item.details?.external_name ||
                  "未填写姓名"}
                （
                {item.details?.linked_org ||
                  item.details?.external_org ||
                  "未填写组织"}
                ）；确定日期：{item.occurred_on || "未登记"}
                {item.details?.external
                  ? "；外部正式党员（已人工核验）"
                  : ""}
              </p>
            ))}
            <p>
              入党介绍人一般由两名正式党员担任；优先关联本校正式党员档案，外部正式党员须人工核验。
            </p>
          </div>
          {canRegisterBranch && (
            <button
              type="button"
              className="button secondary"
              disabled={disabled}
              onClick={() => onRegister("introducer")}
            >
              登记入党介绍人
            </button>
          )}
        </div>

        <div className="development-gate-card">
          <span className="metric-icon blue">
            <ClipboardText size={22} />
          </span>
          <div>
            <h3>
              支委会审查{" "}
              <Badge tone={procedureTone(branch)}>
                {procedureStatusLabel(branch)}
              </Badge>
            </h3>
            <p>{branch.notice || "尚未登记支委会审查"}</p>
            {branch.current && (
              <p>
                审查日期：{branch.current.occurred_on || "未登记"}；审查意见：
                {branch.current.summary || "未填写"}；参加人员：
                {branch.current.details?.attendees || "未登记"}
              </p>
            )}
            <p>
              支委会审查由支部委员会形成意见，系统只登记审查结论，不代替支委会研究。
            </p>
          </div>
          {canRegisterBranch && (
            <button
              type="button"
              className="button secondary"
              disabled={disabled}
              onClick={() => onRegister("branch_committee_review")}
            >
              登记支委会审查
            </button>
          )}
        </div>

        <div className="development-gate-card">
          <span className="metric-icon blue">
            <ShieldCheck size={22} />
          </span>
          <div>
            <h3>
              上级党委预审{" "}
              <Badge tone={procedureTone(preReview)}>
                {procedureStatusLabel(preReview)}
              </Badge>
            </h3>
            <p>{preReview.notice || "尚未登记上级党委预审"}</p>
            {preReview.current && (
              <p>
                预审日期：{preReview.current.occurred_on || "未登记"}；上级党组织：
                {preReview.current.details?.upper_org || "未登记"}；批复文号：
                {preReview.current.details?.reply_no || "未登记"}；预审意见：
                {preReview.current.summary || "未填写"}
              </p>
            )}
            <p>
              上级党委预审由上级党组织办理；系统只登记预审事实和批复要素，不替代上级审批。
            </p>
          </div>
          {canRegisterUpper && (
            <button
              type="button"
              className="button secondary"
              disabled={disabled}
              onClick={() => onRegister("upper_pre_review")}
            >
              登记预审结果
            </button>
          )}
        </div>

        <div className="development-gate-card">
          <span className="metric-icon blue">
            <FileText size={22} />
          </span>
          <div>
            <h3>
              入党志愿书{" "}
              <Badge tone={procedureTone(form)}>
                {procedureStatusLabel(form)}
              </Badge>
            </h3>
            <p>{form.notice || "尚未登记入党志愿书"}</p>
            {form.current && (
              <p>
                填写日期：{form.current.occurred_on || "未登记"}；志愿书编号：
                {form.current.details?.form_no || "未登记"}；审核日期：
                {form.current.details?.reviewed_on || "未登记"}
              </p>
            )}
            <p>
              志愿书编号、填写和审核状态按原件登记；支部大会决议仍单独归档，不因登记志愿书自动形成决议。
            </p>
          </div>
          {canRegisterBranch && (
            <button
              type="button"
              className="button secondary"
              disabled={disabled}
              onClick={() => onRegister("application_form")}
            >
              登记入党志愿书
            </button>
          )}
        </div>

        <div className="development-gate-card">
          <span className="metric-icon blue">
            <Clock size={22} />
          </span>
          <div>
            <h3>
              上级党委派人谈话{" "}
              <Badge tone={procedureTone(talk)}>
                {procedureStatusLabel(talk)}
              </Badge>
            </h3>
            <p>{talk.notice || "尚未登记上级党委派人谈话"}</p>
            {talk.current && (
              <p>
                谈话日期：{talk.current.occurred_on || "未登记"}；谈话人：
                {talk.current.details?.talker || "未登记"}；谈话情况：
                {talk.current.summary || "未填写"}
              </p>
            )}
            <p>
              上级党委派人谈话应在上级审批前完成；系统只登记谈话事实，不替代上级审批。
            </p>
          </div>
          {canRegisterUpper && (
            <button
              type="button"
              className="button secondary"
              disabled={disabled}
              onClick={() => onRegister("upper_talk")}
            >
              登记谈话记录
            </button>
          )}
        </div>
      </div>

      {["发展对象", "预备党员", "正式党员"].includes(stage) && (
        <>
          <div className="sub-toolbar">
            <span>支部大会票决与预备党员转正</span>
          </div>
          <div className="procedure-grid">
            <div className="development-gate-card">
              <span className="metric-icon blue">
                <ClipboardText size={22} />
              </span>
              <div>
                <h3>
                  支部大会票决{" "}
                  <Badge tone={procedureTone(branchVote)}>
                    {procedureStatusLabel(branchVote)}
                  </Badge>
                </h3>
                <p>{branchVote.notice || "尚未登记支部大会票决"}</p>
                {branchVote.current && (
                  <p>
                    票决事项：
                    {VOTE_MEETING_LABELS[
                      branchVote.current.details?.meeting_for
                    ] || "支部大会"}
                    ；票决日期：{branchVote.current.occurred_on || "未登记"}；
                    应到/实到：
                    {branchVote.current.details?.eligible_count ?? "—"}/
                    {branchVote.current.details?.attended_count ?? "—"}；
                    同意/不同意/弃权：
                    {branchVote.current.details?.agree_count ?? "—"}/
                    {branchVote.current.details?.disagree_count ?? "—"}/
                    {branchVote.current.details?.abstain_count ?? "—"}；
                    决议：{branchVote.current.summary || "未填写"}
                  </p>
                )}
                <p>
                  票决结果由组织人员按会议记录登记，系统不按票数自动判定通过。
                </p>
              </div>
              {canRegisterBranch && (
                <button
                  type="button"
                  className="button secondary"
                  disabled={disabled}
                  onClick={() => onRegister("branch_vote")}
                >
                  {stage === "发展对象" ? "登记接收票决" : "登记支部大会票决"}
                </button>
              )}
            </div>

            {["预备党员", "正式党员"].includes(stage) && (
              <div className="development-gate-card">
                <span className="metric-icon blue">
                  <ShieldCheck size={22} />
                </span>
                <div>
                  <h3>
                    预备党员转正结果{" "}
                    <Badge tone={procedureTone(outcome)}>
                      {procedureStatusLabel(outcome)}
                    </Badge>
                  </h3>
                  <p>{outcome.notice || "尚未登记预备党员转正结果"}</p>
                  {outcome.current && (
                    <p>
                      决定日期：{outcome.current.occurred_on || "未登记"}；
                      结论：{outcome.current.summary || "未填写"}
                      {outcome.current.details?.effective_until
                        ? `；延长至 ${outcome.current.details.effective_until}`
                        : ""}
                    </p>
                  )}
                  <p>
                    按期转正、延长预备期和取消预备党员资格均按组织结论登记；延长预备期不是新阶段。
                  </p>
                </div>
                {canRegisterBranch && (
                  <button
                    type="button"
                    className="button secondary"
                    disabled={disabled}
                    onClick={() => onRegister("probation_outcome")}
                  >
                    登记转正结果
                  </button>
                )}
              </div>
            )}
          </div>
        </>
      )}

      {["预备党员", "正式党员"].includes(stage) && (
        <>
          <div className="sub-toolbar">
            <span>预备党员后续事项</span>
          </div>
          <div className="procedure-grid">
            <div className="development-gate-card">
              <span className="metric-icon blue">
                <FileText size={22} />
              </span>
              <div>
                <h3>
                  再上一级党委组织部门备案{" "}
                  <Badge tone={procedureTone(higherRecord)}>
                    {procedureStatusLabel(higherRecord)}
                  </Badge>
                </h3>
                <p>
                  {higherRecord.notice ||
                    "尚未登记再上一级党委组织部门备案"}
                </p>
                {higherRecord.current && (
                  <p>
                    备案日期：{higherRecord.current.occurred_on || "未登记"}；
                    上级党组织：{higherRecord.current.details?.upper_org || "未登记"}；
                    批复文号：{higherRecord.current.details?.reply_no || "未登记"}
                  </p>
                )}
                <p>
                  仅登记备案事实和批复要素，不代替再上一级党委组织部门办理。
                </p>
              </div>
              {canRegisterUpper && (
                <button
                  type="button"
                  className="button secondary"
                  disabled={disabled}
                  onClick={() => onRegister("higher_record")}
                >
                  登记备案
                </button>
              )}
            </div>

            <div className="development-gate-card">
              <span className="metric-icon blue">
                <UserCircle size={22} />
              </span>
              <div>
                <h3>
                  编入党支部和党小组{" "}
                  <Badge tone={procedureTone(partyGroup)}>
                    {procedureStatusLabel(partyGroup)}
                  </Badge>
                </h3>
                <p>
                  {partyGroup.notice || "尚未登记编入党支部和党小组"}
                </p>
                {partyGroup.current && (
                  <p>
                    编入日期：{partyGroup.current.occurred_on || "未登记"}；
                    党支部：{partyGroup.current.details?.party_branch || "未登记"}；
                    党小组：{partyGroup.current.details?.party_group || "未登记"}
                  </p>
                )}
                <p>
                  编入党支部和党小组由支部办理；系统只做轻量登记，不建立独立模块。
                </p>
              </div>
              {canRegisterBranch && (
                <button
                  type="button"
                  className="button secondary"
                  disabled={disabled}
                  onClick={() => onRegister("party_group")}
                >
                  登记编组
                </button>
              )}
            </div>

            {stage === "预备党员" && (
              <div className="development-gate-card">
                <span className="metric-icon blue">
                  <CheckCircle size={22} />
                </span>
                <div>
                  <h3>
                    入党宣誓 <Badge tone="orange">待组织</Badge>
                  </h3>
                  <p>
                    入党宣誓由党组织安排，系统只做提醒，不建立独立宣誓模块。
                  </p>
                  <p>
                    宣誓完成后，请在“流程看板”中由具备阶段办理权限的人员标记已宣誓。
                  </p>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}

export function DevelopmentWorkbench() {
  const { session, navigate, routeParams } = useApp();
  const { data, update, notify } = useStore();
  const w = useManagedWorkspace();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(routeParams.profileId || "");
  const [tab, setTab] = useState(routeParams.tab || "材料清单");
  const [profile, setProfile] = useState(null);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  const [board, setBoard] = useState(null);
  const [boardLoading, setBoardLoading] = useState(false);
  const [boardError, setBoardError] = useState(null);
  const [resolvedDemoReminders, setResolvedDemoReminders] = useState([]);
  const materialDraft = useMaterialDraft({ material_type: "", document_date: "" });
  const people = w.members.filter(
    (p) =>
      p.name.includes(query) &&
      (!routeParams.department || p.department === routeParams.department) &&
      (!routeParams.orgId || p.orgId === routeParams.orgId) &&
      (!routeParams.stage || p.stage === routeParams.stage),
  );
  const member =
    people.find((p) => p.id === selected) ||
    people.find((p) => p.stage !== "正式党员") ||
    people[0];
  useEffect(() => {
    if (!IS_LIVE || !member) return;
    let active = true;
    setProfile(null);
    setError(null);
    setBusy(true);
    roleApi
      .profile(member.id)
      .then((p) => {
        if (active) setProfile(p);
      })
      .catch((e) => {
        if (active) setError(e);
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [member?.id, tick, session.user.id]);
  useEffect(() => {
    if (!IS_LIVE || tab !== "流程看板") return;
    let active = true;
    setBoardLoading(true);
    setBoardError(null);
    roleApi
      .flowBoard()
      .then((result) => {
        if (active) setBoard(result);
      })
      .catch((e) => {
        if (active) setBoardError(e);
      })
      .finally(() => {
        if (active) setBoardLoading(false);
      });
    return () => {
      active = false;
    };
  }, [tab, tick, session.user.id]);
  const detail = member
    ? IS_LIVE
      ? profile?.id === member.id
        ? profile
        : null
      : getDemoDevelopment(member, data.developmentProfiles[member.id])
    : null;
  const materials = detail?.materials || [];
  const eligibility = detail
    ? leagueEligibility(detail.birth_date, detail.league_joined_on)
    : null;
  // 个人提交材料只在清单里展示来源，不参与发展材料核对与阶段流转。
  const developmentMaterials = materials.filter(
    (m) => materialSource(m) !== "personal",
  );
  const stage = IS_LIVE
    ? STAGE_LABELS[detail?.current_stage] || member?.stage
    : member?.stage;
  const politicalState = detail?.political_reviews || {
    items: [],
    current: null,
    satisfied: false,
    notice: "尚未登记政治审查结论",
    requirement: "接收预备党员前须有组织形成的政审合格结论",
  };
  const trainingState = detail?.trainings || {
    items: [],
    best: null,
    satisfied: false,
    notice: "尚未登记集中培训",
    requirement: "集中培训不少于 3 天或 24 学时",
  };
  const procedureState = detail?.procedures || emptyProcedureState();
  const flowBoardData = IS_LIVE
    ? board
    : buildDemoFlowBoard(
        w.members,
        data.developmentProfiles,
        resolvedDemoReminders,
      );
  const canResolveReminder = hasPermission(session, "member.stage_transition");
  const canRegisterBranchProcedure = ["branch_secretary", "organizer"].includes(
    session.user.role,
  );
  const canRegisterUpperProcedure = ["school_admin", "department_admin"].includes(
    session.user.role,
  );
  const formalMembers = w.members.filter(
    (p) => p.stage === "正式党员" && p.id !== member?.id,
  );
  const conversionVoteReady =
    procedureState.branch_vote?.current?.status === "passed" &&
    procedureState.branch_vote?.current?.details?.meeting_for === "conversion";
  const procedureGaps = [
    !procedureState.contacts.satisfied && "培养联系人",
    !procedureState.introducers.satisfied && "入党介绍人",
    !procedureState.branch_committee_review.satisfied && "支委会审查",
    !procedureState.upper_pre_review.satisfied && "上级党委预审",
    !procedureState.application_form.satisfied && "入党志愿书",
  ].filter(Boolean);
  const approvedMaterialTypes = new Set(
    developmentMaterials
      .filter((material) => material.review_status === "approved")
      .map((material) => material.material_type),
  );
  const canRegisterMaterials = session.user.role !== "school_admin";
  const canRegisterGates = ["发展对象", "预备党员", "正式党员"].includes(stage);
  const transitionShortcuts = [];
  function addTransitionShortcut(label, action) {
    if (!transitionShortcuts.some((item) => item.label === label))
      transitionShortcuts.push({ label, ...action });
  }
  function addProcedureShortcut(kind, label, allowed) {
    if (allowed)
      addTransitionShortcut(label, { type: "procedure", kind });
  }
  function addMaterialShortcut(materialType) {
    if (!canRegisterMaterials || approvedMaterialTypes.has(materialType)) return;
    addTransitionShortcut(`补交${materialType}`, {
      type: "material",
      materialType,
    });
  }
  function addGateShortcut(modalName, label) {
    if (canRegisterGates && session.user.role !== "school_admin")
      addTransitionShortcut(label, { type: "modal", modalName });
  }
  if (stage === "入党申请人") {
    addMaterialShortcut("入党申请书");
    addMaterialShortcut("党组织谈话记录");
  }
  if (stage === "入党积极分子") {
    addProcedureShortcut(
      "contact",
      "去登记培养联系人",
      canRegisterBranchProcedure && !procedureState.contacts?.satisfied,
    );
    [
      "思想汇报",
      "培养考察记录",
      "群众评议材料",
      "党课培训证明",
    ].forEach(addMaterialShortcut);
  }
  if (stage === "发展对象") {
    addProcedureShortcut(
      "contact",
      "去登记培养联系人",
      canRegisterBranchProcedure && !procedureState.contacts?.satisfied,
    );
    addProcedureShortcut(
      "introducer",
      "去登记入党介绍人",
      canRegisterBranchProcedure && !procedureState.introducers?.satisfied,
    );
    addProcedureShortcut(
      "branch_committee_review",
      "去登记支委会审查",
      canRegisterBranchProcedure && !procedureState.branch_committee_review?.satisfied,
    );
    addProcedureShortcut(
      "upper_pre_review",
      "去登记上级党委预审",
      canRegisterUpperProcedure && !procedureState.upper_pre_review?.satisfied,
    );
    addProcedureShortcut(
      "application_form",
      "去登记入党志愿书",
      canRegisterBranchProcedure && !procedureState.application_form?.satisfied,
    );
    if (!politicalState.satisfied) addGateShortcut("political", "去登记政治审查");
    if (!trainingState.satisfied) addGateShortcut("training", "去登记集中培训");
    ["政治审查材料", "公示情况报告", "支部大会决议"].forEach(
      addMaterialShortcut,
    );
  }
  if (stage === "预备党员") {
    addProcedureShortcut(
      "branch_vote",
      "去登记支部大会转正票决",
      canRegisterBranchProcedure && !conversionVoteReady,
    );
    const outcome = procedureState.probation_outcome?.current;
    addProcedureShortcut(
      "probation_outcome",
      "去登记转正结果",
      canRegisterBranchProcedure && outcome?.status !== "qualified",
    );
    ["转正申请书", "预备期考察记录", "支部大会决议"].forEach(
      addMaterialShortcut,
    );
  }
  function openTransitionShortcut(shortcut) {
    setError(null);
    if (shortcut.type === "procedure") {
      setTab("发展程序");
      setModal({ type: "procedure", kind: shortcut.kind });
      return;
    }
    if (shortcut.type === "material") {
      materialDraft.reset();
      materialDraft.edit("material_type", shortcut.materialType);
      setTab("材料清单");
      setModal("material");
      return;
    }
    setTab("培养记录");
    setModal(shortcut.modalName);
  }
  const stageJoinedOn = dateOnly(
    detail?.stage_joined_on || member?.stage_joined_on || member?.joined,
  );
  const applicationDate = developmentMaterials
    .filter(
      (material) =>
        material.material_type === "入党申请书" &&
        material.review_status === "approved" &&
        material.document_date,
    )
    .map((material) => dateOnly(material.document_date))
    .sort()[0];
  const probationOutcome = procedureState.probation_outcome?.current;
  let earliestDate = null;
  if (stage === "入党申请人" && applicationDate)
    earliestDate = addCalendarMonths(applicationDate, 6);
  if (stage === "入党积极分子" && stageJoinedOn)
    earliestDate = addCalendarDays(stageJoinedOn, 365);
  if (stage === "预备党员") {
    earliestDate =
      probationOutcome?.status === "extended" &&
      probationOutcome.details?.effective_until
        ? dateOnly(probationOutcome.details.effective_until)
        : addCalendarDays(stageJoinedOn, 365);
  }
  const remainingDays = daysUntil(earliestDate);
  const receptionVote = procedureState.branch_vote?.current;
  const wizardChecks = {
    application: approvedMaterialTypes.has("入党申请书"),
    talk: approvedMaterialTypes.has("党组织谈话记录"),
    contact: Boolean(procedureState.contacts?.satisfied),
    cultivation: Boolean(detail?.cultivation?.length),
    introducer: Boolean(procedureState.introducers?.satisfied),
    political: Boolean(politicalState.satisfied),
    training: Boolean(trainingState.satisfied),
    branch_review: Boolean(procedureState.branch_committee_review?.satisfied),
    upper_pre_review: Boolean(procedureState.upper_pre_review?.satisfied),
    application_form: Boolean(procedureState.application_form?.satisfied),
    reception_vote:
      receptionVote?.status === "passed" &&
      receptionVote?.details?.meeting_for === "reception",
    upper_talk: Boolean(procedureState.upper_talk?.satisfied),
    higher_record: Boolean(procedureState.higher_record?.satisfied),
    party_group: Boolean(procedureState.party_group?.satisfied),
    transfer_application: approvedMaterialTypes.has("转正申请书"),
    conversion:
      conversionVoteReady && probationOutcome?.status === "qualified",
  };
  const stageGroupIndex = DEVELOPMENT_STEP_GROUPS.indexOf(stage);
  const wizardSteps = DEVELOPMENT_STEPS.map((step) => {
    let state = "pending";
    if (stageGroupIndex >= 0) {
      if (stageGroupIndex > step.group) state = "done";
      else if (stageGroupIndex < step.group) state = "pending";
      else if (!step.check) state = "current";
      else if (["upper", "oath", "continued", "archive"].includes(step.check))
        state = "check";
      else state = wizardChecks[step.check] ? "done" : "current";
    }
    return { ...step, state };
  });
  const wizardNextAction =
    stage === "正式党员"
      ? "继续教育管理"
      : transitionShortcuts[0]?.label || "完成当前阶段材料与程序";
  const politicalMaterials = developmentMaterials.filter(
    (m) => m.material_type === "政治审查材料" && m.review_status === "approved",
  );
  const trainingMaterials = developmentMaterials.filter(
    (m) => m.material_type === "党课培训证明" && m.review_status === "approved",
  );
  const canTransition =
    (STAGES.includes(stage) && stage !== "正式党员") || stage === "退回";
  // 完整政审结论只给有阶段办理权限的角色；后端读取出口已按权限脱敏，这里同时兜住演示数据。
  const canReadPoliticalConclusion = hasPermission(
    session,
    "member.stage_transition",
  );
  function saveDemoProfile(next) {
    update("developmentProfiles", (prev) => ({ ...prev, [member.id]: next }));
  }
  async function save(e) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const f = new FormData(e.currentTarget);
    try {
      if (
        !hasPermission(session, "member.stage_transition") ||
        !member ||
        (!IS_LIVE && !memberInScope(session.user, member))
      )
        throw new Error("当前档案不在办理权限范围。");
      if (!detail) throw new Error("档案尚未加载完成，请重试。");
      const reason = String(f.get("reason") || "").trim();
      if (modal === "profile") {
        const birth_date = f.get("birth_date") || null;
        const league_joined_on = f.get("league_joined_on") || null;
        if (!birth_date && !league_joined_on)
          throw new Error("请至少填写出生年月或入团时间。");
        if (birth_date && league_joined_on && league_joined_on < birth_date)
          throw new Error("入团时间不能早于出生年月。");
        if (IS_LIVE) {
          await roleApi.updateProfile(member.id, {
            ...(birth_date ? { birth_date } : {}),
            ...(league_joined_on ? { league_joined_on } : {}),
            reason,
          });
          w.reload();
        } else {
          saveDemoProfile({
            ...detail,
            ...(birth_date ? { birth_date } : {}),
            ...(league_joined_on ? { league_joined_on } : {}),
          });
        }
      } else if (modal === "link") {
        const username = f.get("username").trim();
        if (IS_LIVE) {
          await roleApi.linkAccount(member.id, username);
          w.reload();
        } else
          update(
            "accounts",
            linkDemoAccount(session, member, data.accounts, username),
          );
      } else if (modal === "material") {
        const body = {
          material_type: f.get("material_type"),
          file_version: f.get("file_version").trim(),
          document_date: f.get("document_date") || null,
          submit_date: f.get("submit_date") || null,
          reason,
        };
        if (body.material_type === "入党申请书" && !body.document_date)
          throw new Error("入党申请书须填写落款日期，用于核验申请时年满18周岁和申请满6个月。");
        if (IS_LIVE) {
          if (materialDraft.file) {
            validateMaterialFile(materialDraft.file, 10 * 1024 * 1024);
            await roleApi.archiveMaterial(member.id, { ...body, file: materialDraft.file });
          } else await roleApi.addMaterial(member.id, body);
        }
        else
          saveDemoProfile({
            ...detail,
            materials: [
              ...materials,
              {
                ...body,
                id: crypto.randomUUID(),
                review_status: "pending",
                note: "组织人员人工登记，待核验",
              },
            ],
          });
      } else if (modal === "cultivation") {
        const body = {
          profile_id: member.id,
          category: f.get("category"),
          score: f.get("score") === "" ? null : Number(f.get("score")),
          period: f.get("period").trim(),
          source_note: f.get("source_note").trim(),
          is_risk: false,
          risk_note: "",
        };
        if (IS_LIVE) await roleApi.cultivation(member.id, body);
        else
          saveDemoProfile({
            ...detail,
            cultivation: [
              ...detail.cultivation,
              { ...body, id: crypto.randomUUID() },
            ],
          });
      } else if (modal === "political") {
        const status = f.get("status");
        const body = {
          status,
          reviewed_on: f.get("reviewed_on"),
          scope: f.get("scope").trim(),
          conclusion: f.get("conclusion").trim(),
          note: f.get("note").trim(),
          material_id: f.get("material_id") || null,
          reason,
        };
        if (!body.scope) throw new Error("请填写政治审查范围。");
        if (body.reviewed_on > todayIso())
          throw new Error("政审日期不能晚于今天。");
        if (status !== "in_progress" && !body.conclusion)
          throw new Error("作出政审结论时须填写结论内容。");
        if (IS_LIVE) {
          await roleApi.addPoliticalReview(member.id, body);
          w.reload();
        } else {
          const record = {
            ...body,
            id: crypto.randomUUID(),
            status_label:
              { in_progress: "审查中", passed: "合格", failed: "不合格" }[status] ||
              "状态待核对",
            reviewed_by: session.user.name,
            created_at: new Date().toISOString(),
            data_level: "sensitive",
          };
          const items = [
            record,
            ...(detail.political_reviews?.items || []),
          ].sort(
            (a, b) =>
              String(b.reviewed_on || "").localeCompare(
                String(a.reviewed_on || ""),
              ) ||
              String(b.created_at || "").localeCompare(
                String(a.created_at || ""),
              ),
          );
          const current = items[0];
          saveDemoProfile({
            ...detail,
            political_reviews: {
              ...(detail.political_reviews || {}),
              items,
              current,
              satisfied: current.status === "passed",
              notice:
                current.status === "passed"
                  ? "政治审查结论为合格"
                  : current.status === "failed"
                    ? "政治审查结论为不合格，不能办理接收预备党员"
                    : "政治审查进行中，尚未形成结论",
            },
          });
        }
      } else if (modal === "training") {
        const start_on = f.get("start_on");
        const end_on = f.get("end_on");
        const days = f.get("days") === "" ? null : Number(f.get("days"));
        const hours = f.get("hours") === "" ? null : Number(f.get("hours"));
        if (end_on < start_on) throw new Error("培训结束日期不能早于开始日期。");
        if (!(days > 0) && !(hours > 0))
          throw new Error("请填写培训天数或学时，至少一项大于0。");
        const body = {
          training_type: "centralized",
          start_on,
          end_on,
          days,
          hours,
          issuer: f.get("issuer").trim(),
          certificate_material_id: f.get("certificate_material_id") || null,
          note: f.get("note").trim(),
          reason,
        };
        if (IS_LIVE) {
          await roleApi.addTraining(member.id, body);
          w.reload();
        } else {
          const meets = (days || 0) >= 3 || (hours || 0) >= 24;
          const record = {
            ...body,
            id: crypto.randomUUID(),
            meets_requirement: meets,
            created_by: session.user.name,
          };
          const items = [record, ...(detail.trainings?.items || [])];
          const qualified = items.filter((item) => item.meets_requirement);
          const best = (qualified.length ? qualified : items).reduce(
            (current, item) =>
              !current ||
              (item.days || 0) > (current.days || 0) ||
              ((item.days || 0) === (current.days || 0) &&
                (item.hours || 0) > (current.hours || 0))
                ? item
                : current,
            null,
          );
          const satisfied = qualified.length > 0;
          saveDemoProfile({
            ...detail,
            trainings: {
              ...(detail.trainings || {}),
              items,
              best,
              satisfied,
              notice: satisfied
                ? "已登记集中培训达到 3 天 / 24 学时要求"
                : items.length
                  ? "集中培训未达 3 天或 24 学时，请补充培训记录"
                  : "尚未登记集中培训",
            },
          });
        }
      } else if (modal?.type === "procedure") {
        const kind = modal.kind;
        const occurred_on = f.get("occurred_on");
        const status = f.get("status") || "";
        const summary = (f.get("summary") || "").trim();
        const note = (f.get("note") || "").trim();
        const title = f.get("title") || "";
        if (!occurred_on) throw new Error("请填写程序日期。");
        if (occurred_on > todayIso()) throw new Error("程序日期不能晚于今天。");
        const details = {};
        if (kind === "contact" || kind === "introducer") {
          const linkedId = f.get("linked_profile_id") || "";
          const externalName = f.get("external_name").trim();
          const externalOrg = f.get("external_org").trim();
          const externalTitle = f.get("external_title").trim();
          const verifiedOn = f.get("verified_on") || "";
          if (!linkedId && !externalName)
            throw new Error("请选择档案内正式党员，或填写外部正式党员姓名。");
          if (!linkedId && (!externalOrg || !verifiedOn || !note))
            throw new Error("外部正式党员须填写所在组织、核验日期和核验依据。");
          details.linked_profile_id = linkedId;
          details.external_name = externalName;
          details.external_org = externalOrg;
          details.external_title = externalTitle;
          details.verified_on = verifiedOn;
          const linked = linkedId
            ? w.members.find((p) => p.id === linkedId)
            : null;
          details.linked_name = linked?.name || "";
          details.linked_org = linked?.organization || linked?.org_name || "";
          details.external = !linkedId;
        } else if (kind === "branch_committee_review") {
          details.attendees = f.get("attendees").trim();
          if (status !== "in_progress" && !summary)
            throw new Error("作出审查结论时须填写审查意见。");
        } else if (kind === "upper_pre_review") {
          details.upper_org = f.get("upper_org").trim();
          details.reply_no = f.get("reply_no").trim();
          if (!details.upper_org) throw new Error("请填写上级党组织。");
          if (status !== "in_progress" && !summary)
            throw new Error("作出预审结论时须填写预审意见。");
        } else if (kind === "application_form") {
          details.form_no = f.get("form_no").trim();
          details.reviewed_on = f.get("reviewed_on") || "";
          if (details.reviewed_on && details.reviewed_on < occurred_on)
            throw new Error("审核日期不能早于填写日期。");
          if (status === "reviewed" && (!details.form_no || !details.reviewed_on))
            throw new Error("志愿书审核通过时须填写编号和审核日期。");
        } else if (kind === "upper_talk") {
          details.talker = f.get("talker").trim();
          details.talker_org = f.get("talker_org").trim();
          if (!details.talker) throw new Error("请填写谈话人。");
          if (!summary) throw new Error("请填写谈话情况。");
        } else if (kind === "branch_vote") {
          details.meeting_for = f.get("meeting_for") || "conversion";
          const rawCounts = [
            "eligible_count",
            "attended_count",
            "agree_count",
            "disagree_count",
            "abstain_count",
          ];
          for (const field of rawCounts) {
            const raw = String(f.get(field) ?? "").trim();
            if (!raw) throw new Error("请填写应到、实到和各项票数。");
            details[field] = Number(raw);
          }
          if (!summary) throw new Error("请填写票决结果和决议内容。");
          if (details.attended_count > details.eligible_count)
            throw new Error("实到人数不能大于应到人数。");
          if (
            details.agree_count +
              details.disagree_count +
              details.abstain_count >
            details.attended_count
          )
            throw new Error("同意、不同意和弃权票数之和不能大于实到人数。");
        } else if (kind === "probation_outcome") {
          details.effective_until =
            status === "extended" ? f.get("effective_until") || "" : "";
          if (status === "extended" && !details.effective_until)
            throw new Error("延长预备期须填写截止日期。");
          if (details.effective_until && details.effective_until <= occurred_on)
            throw new Error("延长预备期截止日期须晚于本次决定日期。");
          if (!summary) throw new Error("请填写组织形成的转正结论。");
        } else if (kind === "higher_record") {
          details.upper_org = f.get("upper_org").trim();
          details.reply_no = f.get("reply_no").trim();
          if (!details.upper_org) throw new Error("请填写上级党组织。");
        } else if (kind === "party_group") {
          details.party_branch = f.get("party_branch").trim();
          details.party_group = f.get("party_group").trim();
          details.assigned_on = occurred_on;
          if (!details.party_group) throw new Error("请填写党小组。");
        }
        const body = {
          kind,
          occurred_on,
          status,
          title,
          summary,
          note,
          reason,
          details,
        };
        if (IS_LIVE) {
          await roleApi.addProcedure(member.id, body);
          w.reload();
        } else {
          const record = {
            ...body,
            title:
              title ||
              {
                contact: "培养联系人",
                introducer: "入党介绍人",
                branch_vote: "支部大会票决",
                probation_outcome: "预备党员转正结果",
                higher_record: "再上一级党委组织部门备案",
                party_group: "编入党支部和党小组",
              }[kind] ||
              "",
            status:
              kind === "contact"
                ? "assigned"
                : kind === "introducer"
                  ? "confirmed"
                  : kind === "upper_talk"
                    ? "completed"
                    : kind === "higher_record"
                      ? "recorded"
                      : kind === "party_group"
                        ? "assigned"
                        : status,
            id: crypto.randomUUID(),
            created_at: new Date().toISOString(),
            created_by: session.user.name,
            data_level: [
              "branch_committee_review",
              "upper_pre_review",
              "upper_talk",
              "branch_vote",
              "probation_outcome",
            ].includes(kind)
              ? "sensitive"
              : "internal",
            revision:
              (procedureState[
                kind === "contact"
                  ? "contacts"
                  : kind === "introducer"
                    ? "introducers"
                    : kind
              ]?.items?.length || 0) + 1,
          };
          saveDemoProfile({
            ...detail,
            procedures: addDemoProcedure(detail.procedures, record),
          });
        }
      } else if (modal === "transition") {
        const target = f.get("target_stage"),
          basis = f.get("basis").trim(),
          opinion = f.get("opinion").trim(),
          decision_date = f.get("decision_date");
        if (decision_date > new Date().toISOString().slice(0, 10))
          throw new Error("办理日期不能晚于今天。");
        if (IS_LIVE) {
          await roleApi.transition(member.id, {
            target_stage: Object.keys(STAGE_LABELS).find(
              (k) => STAGE_LABELS[k] === target,
            ),
            decision_date,
            basis,
            opinion,
          });
          w.reload();
        } else {
          const next = transitionDemoMember(
            session,
            member,
            target,
            basis,
            opinion,
            decision_date,
          );
          update("members", (prev) =>
            prev.map((p) => (p.id === member.id ? next : p)),
          );
          saveDemoProfile({
            ...detail,
            stage_history: [
              ...detail.stage_history,
              {
                id: crypto.randomUUID(),
                from_stage: member.stage,
                to_stage: target,
                decision_date,
                basis,
                opinion,
                decided_by: session.user.name,
              },
            ],
          });
        }
      }
      if (!IS_LIVE)
        update("auditEntries", (prev) => [
          newAudit(
            session.user,
            modal === "profile"
              ? "补录党员档案信息"
              : modal === "link"
                ? "明确关联本人档案账号"
                : modal === "transition"
                  ? "人工登记发展阶段"
                : modal === "material"
                  ? "登记发展材料"
                : modal === "political"
                  ? "登记政治审查结论"
                : modal === "training"
                  ? "登记集中培训"
                : modal?.type === "procedure"
                  ? "登记发展程序事实"
                  : "登记培养记录",
            "member_profile",
            member.id,
          ),
          ...prev,
        ]);
      setModal(null);
      setTick((t) => t + 1);
      notify(
        modal === "political"
          ? "政治审查结论已登记"
          : modal === "training"
            ? "集中培训记录已登记"
            : modal === "material"
              ? "发展材料已登记"
              : modal === "transition"
                ? "阶段变更已登记"
                : modal?.type === "procedure"
                  ? "发展程序记录已登记"
                  : "办理记录已保存",
      );
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function check() {
    try {
      if (IS_LIVE) {
        const result = await roleApi.checkArchive(member.id);
        setModal({
          type: "check",
          missing: result.result?.missing || [],
          note: result.note,
        });
      } else
        setModal({
          type: "check",
          missing: developmentMaterials
            .filter((m) => m.review_status !== "approved")
            .map((m) => m.material_type),
          note: "当前仅核对已登记材料的状态，完整性结论须由组织人员核验原件后确认。",
        });
    } catch (e) {
      setError(e);
    }
  }
  async function reviewMaterial(m) {
    setError(null);
    if (!hasPermission(session, "member.stage_transition")) return;
    setModal({ type: "review-material", material: m });
  }
  async function decideMaterial(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      const note = f.get("note").trim(),
        review_status = f.get("review_status"),
        document_date = f.get("document_date") || null;
      if (!note) throw new Error("请填写核验意见。");
      if (
        review_status === "approved" &&
        modal.material.material_type === "入党申请书" &&
        !document_date &&
        !modal.material.document_date
      )
        throw new Error("请补录入党申请书落款日期后再核验通过。");
      if (IS_LIVE)
        await roleApi.reviewMaterial(modal.material.id, {
          review_status,
          note,
          reason: note,
          ...(document_date ? { document_date } : {}),
        });
      else {
        saveDemoProfile({
          ...detail,
          materials: materials.map((m) =>
            m.id === modal.material.id
              ? {
                  ...m,
                  review_status,
                  note,
                  document_date: document_date || m.document_date,
                }
              : m,
          ),
        });
        update("auditEntries", (prev) => [
          newAudit(
            session.user,
            "核验发展材料",
            "member_material",
            modal.material.id,
          ),
          ...prev,
        ]);
      }
      setModal(null);
      setTick((t) => t + 1);
      notify("材料核验已登记");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title="党员发展办理"
        subtitle="材料、培养与人工流转集中办理，所有结论保留依据"
      />
      <div className="development-layout">
        <aside className="person-selector">
          <SearchInput
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索培养对象姓名"
          />
          <div className="person-selector-list">
            {people.slice(0, 50).map((p) => (
              <button
                key={p.id}
                className={member?.id === p.id ? "active" : ""}
                onClick={() => {
                  setSelected(p.id);
                  setError(null);
                }}
              >
                <span>{p.name[0]}</span>
                <div>
                  <h3>{p.name}</h3>
                  <p>{p.organization}</p>
                </div>
                <Badge
                  tone={
                    p.stage === "正式党员"
                      ? "green"
                      : p.stage === "取消预备党员资格"
                        ? "red"
                        : "orange"
                  }
                >
                  {p.stage}
                </Badge>
              </button>
            ))}
            {!people.length && !w.loading && <Empty title="暂无授权档案" />}
          </div>
        </aside>
        <div className="development-main">
          {(error || w.error) && !modal && (
            <ErrorBox error={error || w.error} retry={w.reload} />
          )}{" "}
          {tab === "流程看板" ? (
            <>
              <Tabs
                items={DEVELOPMENT_TABS}
                active={tab}
                onChange={setTab}
              />
              <FlowBoard
                board={flowBoardData}
                loading={boardLoading}
                error={boardError}
                canResolve={canResolveReminder}
                onSelect={(profileId, targetTab) => {
                  setSelected(profileId);
                  setTab(targetTab || "材料清单");
                  setError(null);
                }}
                onResolve={async (item, reminder) => {
                  try {
                    if (IS_LIVE) {
                      await roleApi.resolveReminder(
                        reminder.id,
                        "已按组织安排完成入党宣誓",
                      );
                      setBoard((prev) =>
                        prev
                          ? {
                              ...prev,
                              items: prev.items.map((row) =>
                                row.id === item.id
                                  ? {
                                      ...row,
                                      reminders: row.reminders.filter(
                                        (entry) => entry.id !== reminder.id,
                                      ),
                                    }
                                  : row,
                              ),
                            }
                          : prev,
                      );
                    } else {
                      setResolvedDemoReminders((prev) => [
                        ...prev,
                        reminder.id,
                      ]);
                    }
                    notify("入党宣誓提醒已办结");
                  } catch (e) {
                    setBoardError(e);
                  }
                }}
                onRefresh={() => setTick((value) => value + 1)}
              />
            </>
          ) : member ? (
            <>
              <div className="development-person">
                <div>
                  <h2>
                    {member.name}
                    <Badge tone="red">{stage}</Badge>
                  </h2>
                  <p>{member.organization}</p>
                </div>
                <div className="development-actions">
                  <button
                    className="button secondary"
                    disabled={!detail || busy}
                    onClick={() => {
                      setModal("profile");
                      setError(null);
                    }}
                  >
                    补录档案信息
                  </button>
                  {session.user.role !== "school_admin" && (
                    <button
                      className="button secondary"
                      disabled={!detail || busy}
                      onClick={() => {
                        setModal("link");
                        setError(null);
                      }}
                    >
                      关联登录账号
                    </button>
                  )}
                  <button
                    className="button secondary"
                    disabled={!detail || busy}
                    onClick={check}
                  >
                    材料核对
                  </button>
                </div>
              </div>
              {stage === "取消预备党员资格" ? (
                <div className="inline-note development-terminal-note">
                  <WarningCircle size={16} />
                  该人员已办理取消预备党员资格，发展阶段终止；已有记录继续保留，不再办理后续阶段流转。
                </div>
              ) : (
                <div className="mini-stage-rail">
                  {STAGES.map((s, i) => (
                    <div
                      key={s}
                      className={i <= STAGES.indexOf(stage) ? "done" : ""}
                    >
                      <CheckCircle
                        size={16}
                        weight={i <= STAGES.indexOf(stage) ? "fill" : "regular"}
                      />
                      <span>{s}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="inline-note">
                <span>出生年月：{detail?.birth_date || "未登记"}</span>
                <span>入团时间：{detail?.league_joined_on || "未登记"}</span>
                <Badge
                  tone={
                    eligibility?.eligible === true
                      ? "green"
                      : eligibility?.eligible === false
                        ? "orange"
                        : "blue"
                  }
                >
                  {eligibility?.eligible === true
                    ? "推优资格已核验"
                    : eligibility?.eligible === false
                      ? "推优资格不符"
                      : "待补录"}
                </Badge>
                <span>{eligibility?.note}</span>
              </div>
              <Tabs
                items={DEVELOPMENT_TABS}
                active={tab}
                onChange={setTab}
              />
              {busy && !modal && <Loading />}
              {tab === "材料清单" ? (
                <>
                  <div className="sub-toolbar">
                    <span>按组织要求核对具体材料</span>
                    {session.user.role !== "school_admin" && (
                      <button
                        className="button primary"
                        disabled={!detail || busy}
                        onClick={() => {
                          materialDraft.reset();
                          setModal("material");
                          setError(null);
                        }}
                      >
                        <Plus size={15} />
                        登记材料
                      </button>
                    )}
                  </div>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>材料类型</th>
                          <th>版本 / 日期</th>
                          <th>核验状态</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {materials.map((m, i) => {
                          const personal = materialSource(m) === "personal";
                          return (
                            <tr key={m.id || i}>
                              <td>
                                {materialTypeLabel(m)}
                                <small className="cell-subtext">
                                  {materialSourceNote(m)}
                                </small>
                              </td>
                              <td>
                                {m.file_version || "—"}
                                {!personal &&
                                m.material_type === "入党申请书" &&
                                !m.document_date ? (
                                  <Badge tone="red">
                                    缺落款日期，核验前补录
                                  </Badge>
                                ) : (
                                  <small className="cell-subtext">
                                    {m.document_date
                                      ? `落款 ${m.document_date}`
                                      : m.submit_date
                                        ? `收到 ${m.submit_date}`
                                        : "未登记"}
                                  </small>
                                )}
                              </td>
                              <td>
                                {personal ? (
                                  <Badge tone="blue">未纳入发展材料</Badge>
                                ) : (
                                  <Badge
                                    tone={
                                      m.review_status === "approved"
                                        ? "green"
                                        : m.review_status === "rejected"
                                          ? "red"
                                          : "orange"
                                    }
                                  >
                                    {
                                      {
                                        approved: "已核验",
                                        pending: "待核验",
                                        rejected: "已退回",
                                      }[m.review_status]
                                    }
                                  </Badge>
                                )}
                              </td>
                              <td>
                                {personal ? (
                                  <button
                                    className="text-button link"
                                    onClick={() =>
                                      navigate("inbox", { profileId: member.id })
                                    }
                                  >
                                    材料接收查阅
                                  </button>
                                ) : (
                                  <>
                                    <button
                                      className="text-button link"
                                      disabled={!m.id}
                                      onClick={() => reviewMaterial(m)}
                                    >
                                      核验
                                    </button>
                                    {IS_LIVE && m.has_file && (
                                      <button
                                        type="button"
                                        className="text-button link separated-action"
                                        onClick={async () => {
                                          try {
                                            downloadBlob(
                                              await roleApi.developmentFile(m.id),
                                              m.file_name ||
                                                `${m.material_type}.bin`,
                                            );
                                          } catch (e) {
                                            notify(e.message, "error");
                                          }
                                        }}
                                      >
                                        下载原件
                                      </button>
                                    )}
                                  </>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                    {!materials.length && <Empty title="暂无登记材料" />}
                  </div>
                  {materials.some((m) => materialSource(m) === "personal") && (
                    <div className="inline-note">
                      个人提交材料在此仅作查阅，不纳入发展材料核验、材料完整性判断和阶段流转。
                    </div>
                  )}
                  <button
                    className="work-guidance-link"
                    onClick={() => navigate("inbox", { profileId: member.id })}
                  >
                    查看该成员提交的个人材料
                    <ArrowRight size={15} />
                  </button>
                </>
              ) : tab === "培养记录" ? (
                <>
                  <div className="sub-toolbar">
                    <span>如实登记学习、实践与培养事实</span>
                    {session.user.role !== "school_admin" && (
                      <button
                        className="button primary"
                        disabled={!detail || busy}
                        onClick={() => {
                          setModal("cultivation");
                          setError(null);
                        }}
                      >
                        <Plus size={15} />
                        登记培养记录
                      </button>
                    )}
                  </div>
                  <div className="cultivation-list">
                    <div className="development-gate-card">
                      <span className="metric-icon blue">
                        <ShieldCheck size={22} />
                      </span>
                      <div>
                        <h3>
                          政治审查{" "}
                          <Badge
                            tone={
                              politicalState.satisfied
                                ? "green"
                                : politicalState.current?.status === "failed"
                                  ? "red"
                                  : politicalState.current
                                    ? "orange"
                                    : "blue"
                            }
                          >
                            {politicalState.current?.status_label || "未登记"}
                          </Badge>
                        </h3>
                        <p>{politicalState.notice}</p>
                        {politicalState.current && (
                          <p>
                            审查日期：{politicalState.current.reviewed_on || "未登记"}；
                            审查范围：{politicalState.current.scope || "未登记"}
                            {canReadPoliticalConclusion &&
                            politicalState.current.conclusion
                              ? `；结论：${politicalState.current.conclusion}`
                              : ""}
                          </p>
                        )}
                        {politicalState.current &&
                          (politicalState.current.conclusion_restricted ||
                            !canReadPoliticalConclusion) && (
                            <p>结论内容仅具有阶段办理权限的角色可见。</p>
                          )}
                        <p>
                          {politicalState.requirement ||
                            "接收预备党员前须有组织形成的政审合格结论；原始政审材料按涉密级管理"}
                        </p>
                      </div>
                      {session.user.role !== "school_admin" && (
                        <button
                          type="button"
                          className="button secondary"
                          disabled={!detail || busy || !canRegisterGates}
                          title={
                            canRegisterGates
                              ? undefined
                              : "确定为发展对象后才能登记政审结论"
                          }
                          onClick={() => {
                            setModal("political");
                            setError(null);
                          }}
                        >
                          {politicalState.current ? "登记新结论" : "登记政审结论"}
                        </button>
                      )}
                    </div>
                    <div className="development-gate-card">
                      <span className="metric-icon blue">
                        <Clock size={22} />
                      </span>
                      <div>
                        <h3>
                          集中培训{" "}
                          <Badge tone={trainingState.satisfied ? "green" : "orange"}>
                            {trainingState.satisfied ? "已达要求" : "未达要求"}
                          </Badge>
                        </h3>
                        <p>{trainingState.notice}</p>
                        {trainingState.best && (
                          <p>
                            计入记录：{trainingState.best.start_on} 至{" "}
                            {trainingState.best.end_on}；
                            {trainingState.best.days != null
                              ? ` ${trainingState.best.days} 天`
                              : ""}
                            {trainingState.best.hours != null
                              ? ` / ${trainingState.best.hours} 学时`
                              : ""}
                            {trainingState.best.issuer
                              ? `；出具单位：${trainingState.best.issuer}`
                              : ""}
                          </p>
                        )}
                        <p>
                          {trainingState.requirement ||
                            "集中培训不少于 3 天或 24 学时；是否计入发展程序仍须人工核验原件"}
                        </p>
                      </div>
                      {session.user.role !== "school_admin" && (
                        <button
                          type="button"
                          className="button secondary"
                          disabled={!detail || busy || !canRegisterGates}
                          title={
                            canRegisterGates
                              ? undefined
                              : "确定为发展对象后才能登记集中培训"
                          }
                          onClick={() => {
                            setModal("training");
                            setError(null);
                          }}
                        >
                          登记集中培训
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="sub-toolbar">
                    <span>学习、实践与培养记录</span>
                  </div>
                  <div className="cultivation-list">
                    {(detail?.cultivation || []).map((c) => (
                      <div key={c.id}>
                        <span className="metric-icon blue">
                          <FileText size={22} />
                        </span>
                        <div>
                          <h3>{c.period}</h3>
                          <p>{c.source_note}</p>
                        </div>
                        {c.score != null && (
                          <Badge tone="blue">{c.score} 分</Badge>
                        )}
                      </div>
                    ))}
                    {!detail?.cultivation?.length && (
                      <Empty
                        title="暂无培养记录"
                        description="登记实际发生的学习与实践，不由系统编造经历。"
                      />
                    )}
                  </div>
                </>
              ) : tab === "发展程序" ? (
                <DevelopmentProcedurePanel
                  state={procedureState}
                  stage={stage}
                  canRegisterBranch={canRegisterBranchProcedure}
                  canRegisterUpper={canRegisterUpperProcedure}
                  disabled={!detail || busy}
                  onRegister={(kind) => {
                    setModal({ type: "procedure", kind });
                    setError(null);
                  }}
                />
              ) : (
                <>
                  {stageGroupIndex >= 0 && (
                    <DevelopmentWizard
                      stage={stage}
                      stageJoinedOn={stageJoinedOn}
                      earliest={earliestDate}
                      remainingDays={remainingDays}
                      nextAction={wizardNextAction}
                      steps={wizardSteps}
                      shortcuts={transitionShortcuts}
                      onShortcut={openTransitionShortcut}
                    />
                  )}
                  <div className="sub-toolbar">
                    <span>阶段变更由组织人员人工办理</span>
                    <button
                      className="button primary"
                      disabled={!detail || busy || !canTransition}
                      onClick={() => {
                        setModal("transition");
                        setError(null);
                      }}
                    >
                      登记阶段变更
                    </button>
                  </div>
                  <div className="cultivation-list">
                    {(detail?.stage_history || []).map((h) => (
                      <div key={h.id}>
                        <IdentificationCard size={25} />
                        <div>
                          <h3>
                            {STAGE_LABELS[h.from_stage] || h.from_stage}{" "}
                            <ArrowRight size={12} />{" "}
                            {STAGE_LABELS[h.to_stage] || h.to_stage}
                          </h3>
                          <p>
                            {h.decision_date} · {h.basis}
                          </p>
                          <p>{h.opinion}</p>
                        </div>
                      </div>
                    ))}
                    {!detail?.stage_history?.length && (
                      <Empty
                        title="尚无阶段变更记录"
                        description="当前阶段以名册登记为准，历史事实不会事后补造。"
                      />
                    )}
                  </div>
                </>
              )}
              <div className="page-note">
                材料核验不自动推进阶段；流转须有真实组织决定和办理依据。
              </div>
            </>
          ) : (
            <Empty title="请选择一位培养对象" />
          )}
        </div>
      </div>
      {typeof modal === "string" && (
        <Modal
          title={
            modal === "profile"
              ? "补录档案信息"
              : modal === "link"
                ? "明确关联登录账号"
                : modal === "material"
                  ? "登记发展材料"
                  : modal === "cultivation"
                    ? "登记培养记录"
                    : modal === "political"
                      ? "登记政治审查结论"
                      : modal === "training"
                        ? "登记集中培训"
                        : "人工登记阶段变更"
          }
          wide
          flat
          onClose={() => !busy && setModal(null)}
        >
          <form onSubmit={save}>
            <div className="form-grid">
              {modal === "profile" ? (
                <>
                  <Field label="出生年月">
                    <input
                      name="birth_date"
                      type="date"
                      max={todayIso()}
                      defaultValue={detail?.birth_date || ""}
                    />
                  </Field>
                  <Field label="入团时间">
                    <input
                      name="league_joined_on"
                      type="date"
                      max={todayIso()}
                      defaultValue={detail?.league_joined_on || ""}
                    />
                  </Field>
                  <div className="inline-note field full">
                    团组织推优按推荐日期核验：年满18周岁、入团满1年。共青团员请填写入团时间；
                    非团员可留空，但无法登记团组织推优。系统不推算、不补造日期。
                  </div>
                  <Field label="补录依据" required full>
                    <textarea
                      name="reason"
                      rows={3}
                      required
                      maxLength={2000}
                      placeholder="填写档案原件、组织核实情况等依据"
                    />
                  </Field>
                </>
              ) : modal === "link" ? (
                <>
                  <Field label="本人登录账号" required full>
                    <input
                      name="username"
                      required
                      maxLength={50}
                      placeholder="输入已核实的同组织党员或申请人账号"
                    />
                  </Field>
                  <div className="inline-note field full">
                    请先核对姓名与档案归属。仅关联同一组织的有效党员或申请人账号，已有不同关联时拒绝覆盖。
                  </div>
                </>
              ) : modal === "material" ? (
                <>
                  <Field label="材料原件（可选，上限 10 MB）" full>
                    <input name="material_file" type="file" accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg" disabled={busy || !IS_LIVE} onChange={(e) => materialDraft.selectFile(e.target.files?.[0] || null)} />
                    {!IS_LIVE && <small>此处仅登记材料清单，原件尚未归档；请按组织要求补充原件。</small>}
                  </Field>
                  <Field label="材料类型" required full>
                    <select name="material_type" required value={materialDraft.draft.material_type} onChange={(e) => materialDraft.edit("material_type", e.target.value)}>
                      <option value="">请选择或采用文档建议</option>
                      {[
                        "入党申请书",
                        "党组织谈话记录",
                        "思想汇报",
                        "培养考察记录",
                        "群众评议材料",
                        "党课培训证明",
                        "政治审查材料",
                        "公示情况报告",
                        "支部大会决议",
                        "上级审批意见",
                        "转正申请书",
                        "预备期考察记录",
                      ].map((t) => (
                        <option key={t}>{t}</option>
                      ))}
                    </select>
                  </Field>
                  <Field label="材料版本" required>
                    <input
                      name="file_version"
                      required
                      maxLength={50}
                      defaultValue="v1"
                    />
                  </Field>
                  <Field label="材料落款日期">
                    <input
                      name="document_date"
                      type="date"
                      max={todayIso()}
                      value={materialDraft.draft.document_date || ""}
                      onChange={(e) =>
                        materialDraft.edit("document_date", e.target.value)
                      }
                    />
                    <small>入党申请书必填，按本人签字日期核验年满18周岁和申请满6个月。</small>
                  </Field>
                  <Field label="组织收到日期">
                    <input
                      name="submit_date"
                      type="date"
                      max={todayIso()}
                      defaultValue={new Date().toISOString().slice(0, 10)}
                    />
                  </Field>
                  <Field label="登记依据" required full>
                    <textarea
                      name="reason"
                      rows={3}
                      required
                      maxLength={materialDraft.file ? 200 : 2000}
                      minLength={materialDraft.file ? 4 : 1}
                    />
                  </Field>
                </>
              ) : modal === "cultivation" ? (
                <>
                  <Field label="培养类型">
                    <select name="category">
                      {Object.entries({
                        theory_test: "理论学习",
                        volunteer_service: "志愿服务",
                        academic: "学业表现",
                        public_review: "群众评议",
                        party_review: "党员评议",
                        other: "其他培养记录",
                      }).map(([v, l]) => (
                        <option value={v} key={v}>
                          {l}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="记录期间" required>
                    <input
                      name="period"
                      defaultValue="2026年10月"
                      required
                      maxLength={100}
                    />
                  </Field>
                  <Field label="分值（可选）">
                    <input
                      name="score"
                      type="number"
                      min="0"
                      max="100"
                      step="0.1"
                    />
                  </Field>
                  <Field label="事实来源与说明" required full>
                    <textarea
                      name="source_note"
                      required
                      rows={4}
                      maxLength={2000}
                    />
                  </Field>
                </>
              ) : modal === "political" ? (
                <>
                  <Field label="审查结论" required>
                    <select name="status" defaultValue="in_progress">
                      <option value="in_progress">审查中</option>
                      <option value="passed">合格</option>
                      <option value="failed">不合格</option>
                    </select>
                  </Field>
                  <Field label="审查日期" required>
                    <input
                      name="reviewed_on"
                      type="date"
                      required
                      max={todayIso()}
                      defaultValue={todayIso()}
                    />
                  </Field>
                  <Field label="审查范围" required full>
                    <input
                      name="scope"
                      required
                      maxLength={200}
                      placeholder="例如：本人及直系亲属、主要社会关系"
                    />
                  </Field>
                  <Field label="结论内容" full>
                    <textarea
                      name="conclusion"
                      rows={3}
                      maxLength={4000}
                      placeholder="作出合格 / 不合格结论时必填；审查中可留空"
                    />
                  </Field>
                  <Field label="关联政治审查材料" full>
                    <select name="material_id" defaultValue="">
                      <option value="">暂不关联（可稍后补）</option>
                      {politicalMaterials.map((m) => (
                        <option value={m.id} key={m.id}>
                          {m.material_type} · {m.file_version || "已归档"}
                        </option>
                      ))}
                    </select>
                    <small>仅列出已核验通过的政治审查材料；原件仍按涉密级管理。</small>
                  </Field>
                  <Field label="备注" full>
                    <textarea name="note" rows={2} maxLength={2000} />
                  </Field>
                  <Field label="登记依据" required full>
                    <textarea
                      name="reason"
                      rows={3}
                      required
                      maxLength={2000}
                      placeholder="填写组织审查过程、结论形成依据等"
                    />
                  </Field>
                </>
              ) : modal === "training" ? (
                <>
                  <Field label="培训开始日期" required>
                    <input name="start_on" type="date" required max={todayIso()} />
                  </Field>
                  <Field label="培训结束日期" required>
                    <input name="end_on" type="date" required max={todayIso()} />
                  </Field>
                  <Field label="培训天数">
                    <input name="days" type="number" min="0" max="365" step="1" />
                  </Field>
                  <Field label="培训学时">
                    <input name="hours" type="number" min="0" max="2000" step="1" />
                  </Field>
                  <Field label="出具单位" full>
                    <input name="issuer" maxLength={200} placeholder="例如：学校党校" />
                  </Field>
                  <Field label="关联培训证明" full>
                    <select name="certificate_material_id" defaultValue="">
                      <option value="">暂不关联（可稍后补）</option>
                      {trainingMaterials.map((m) => (
                        <option value={m.id} key={m.id}>
                          {m.material_type} · {m.file_version || "已归档"}
                        </option>
                      ))}
                    </select>
                    <small>天数或学时至少填写一项；达到 3 天或 24 学时即满足集中培训前置。</small>
                  </Field>
                  <Field label="备注" full>
                    <textarea name="note" rows={2} maxLength={2000} />
                  </Field>
                  <Field label="登记依据" required full>
                    <textarea
                      name="reason"
                      rows={3}
                      required
                      maxLength={2000}
                      placeholder="填写培训通知、结业证明等依据"
                    />
                  </Field>
                </>
              ) : (
                <>
                  <Field label="目标阶段">
                    <select name="target_stage">
                      {stage === "退回" ? (
                        <option>入党积极分子</option>
                      ) : (
                        STAGES.filter(
                          (s, i) => i === STAGES.indexOf(stage) + 1,
                        ).map((s) => (
                          <option key={s}>{s}</option>
                        ))
                      )}
                      {stage === "预备党员" && (
                        <option>取消预备党员资格</option>
                      )}
                    </select>
                  </Field>
                  <Field label="决定日期" required>
                    <input
                      name="decision_date"
                      type="date"
                      required
                      defaultValue={new Date().toISOString().slice(0, 10)}
                      max={new Date().toISOString().slice(0, 10)}
                    />
                  </Field>
                  <Field label="办理依据" required full>
                    <textarea
                      name="basis"
                      required
                      maxLength={2000}
                      rows={3}
                      placeholder="填写真实组织决定、程序及材料依据"
                    />
                  </Field>
                  <Field label="办理意见" required full>
                    <textarea
                      name="opinion"
                      required
                      maxLength={2000}
                      rows={3}
                    />
                  </Field>
                  <div className="inline-note field full">
                    {stage === "入党申请人"
                      ? "转为入党积极分子须有已核验的入党申请书，且落款日期满6个月、申请时年满18周岁。"
                      : stage === "入党积极分子"
                        ? "转为发展对象前应指定培养联系人并完成培养考察；系统仅提示缺项，不替代支委会研究。"
                        : stage === "发展对象"
                          ? `接收预备党员前须有政审合格结论，并完成不少于3天或24学时的集中培训。${
                              procedureGaps.length
                                ? `程序提示：${procedureGaps.join("、")}尚未完成登记；系统仅提示缺项，不替代组织程序。`
                                : ""
                            }`
                          : stage === "预备党员"
                            ? `此操作登记人工决定，不能替代支部讨论、上级审批或其他应履行程序。${
                                !conversionVoteReady
                                  ? "程序提示：支部大会转正票决尚未登记或未通过。"
                                  : ""
                              }${
                                !procedureState.probation_outcome?.current
                                  ? "程序提示：预备党员转正结果尚未登记。"
                                  : procedureState.probation_outcome.current
                                        .status === "extended"
                                    ? `当前为延长预备期至 ${
                                        procedureState.probation_outcome.current
                                          .details?.effective_until || "未登记日期"
                                      }，未满不能办理按期转正。`
                                    : procedureState.probation_outcome.current
                                          .status === "disqualified"
                                      ? "当前转正结果为取消预备党员资格，只能办理对应阶段变更。"
                                      : ""
                              }${
                                !procedureState.upper_talk.satisfied
                                  ? "上级党委派人谈话尚未登记，应在上级审批前完成。"
                                  : ""
                              }`
                            : "此操作登记人工决定，不能替代支部讨论、上级审批或其他应履行程序。"}
                  </div>
                  {transitionShortcuts.length > 0 && (
                    <div className="transition-shortcuts field full">
                      <strong>未达标项快捷补登记</strong>
                      <div className="transition-shortcut-list">
                        {transitionShortcuts.map((shortcut) => (
                          <button
                            type="button"
                            className="button secondary"
                            key={shortcut.label}
                            onClick={() => openTransitionShortcut(shortcut)}
                          >
                            {shortcut.label}
                            <ArrowRight size={14} />
                          </button>
                        ))}
                      </div>
                      <small>
                        点击后直接打开对应登记或材料提交界面；仍需按组织程序办理。
                      </small>
                    </div>
                  )}
                </>
              )}
            </div>
            {modal === "material" && (
              <MaterialSuggestions
                file={materialDraft.file}
                profileId={member.id}
                disabled={busy}
                onApply={(fields) =>
                  materialDraft.apply(
                    { ...fields, document_date: fields.doc_date || "" },
                    ["material_type", "document_date"],
                  )
                }
              />
            )}
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <button
                className="button secondary"
                type="button"
                onClick={() => setModal(null)}
                disabled={busy}
              >
                取消
              </button>
              <button className="button primary" disabled={busy}>
                {busy ? "保存中…" : "保存办理记录"}
              </button>
            </div>
          </form>
        </Modal>
      )}
      {modal?.type === "procedure" && (
        <Modal
          title={
            {
              contact: "登记培养联系人",
              introducer: "登记入党介绍人",
              branch_committee_review: "登记支委会审查",
              upper_pre_review: "登记上级党委预审",
              application_form: "登记入党志愿书",
              upper_talk: "登记上级党委派人谈话",
              branch_vote: "登记支部大会票决",
              probation_outcome: "登记预备党员转正结果",
              higher_record: "登记再上一级党委组织部门备案",
              party_group: "登记编入党支部和党小组",
            }[modal.kind] || "登记发展程序"
          }
          wide
          flat
          onClose={() => !busy && setModal(null)}
        >
          <form onSubmit={save}>
            <div className="form-grid">
              {modal.kind === "contact" || modal.kind === "introducer" ? (
                <>
                  <Field label="角色" full>
                    <select
                      name="title"
                      defaultValue={
                        modal.kind === "contact"
                          ? "培养联系人"
                          : "入党介绍人"
                      }
                    >
                      {modal.kind === "contact" ? (
                        <>
                          <option>培养联系人</option>
                          <option>第一培养联系人</option>
                          <option>第二培养联系人</option>
                        </>
                      ) : (
                        <>
                          <option>入党介绍人</option>
                          <option>第一入党介绍人</option>
                          <option>第二入党介绍人</option>
                        </>
                      )}
                    </select>
                  </Field>
                  <Field label="档案内正式党员" full>
                    <select name="linked_profile_id" defaultValue="">
                      <option value="">不关联（使用外部正式党员）</option>
                      {formalMembers.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} · {p.organization || p.org_name || ""}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <div className="inline-note field full">
                    优先关联本校正式党员档案；关联后由系统带出姓名和组织。外部正式党员须人工核验党员身份，不能仅凭本人陈述登记。
                  </div>
                  <Field label="外部正式党员姓名">
                    <input name="external_name" maxLength={50} />
                  </Field>
                  <Field label="外部正式党员所在组织">
                    <input name="external_org" maxLength={200} />
                  </Field>
                  <Field label="外部正式党员职务">
                    <input name="external_title" maxLength={100} />
                  </Field>
                  <Field label="核验日期">
                    <input
                      name="verified_on"
                      type="date"
                      max={todayIso()}
                    />
                  </Field>
                  <Field
                    label={
                      modal.kind === "contact" ? "指定日期" : "确定日期"
                    }
                    required
                  >
                    <input
                      name="occurred_on"
                      type="date"
                      required
                      max={todayIso()}
                      defaultValue={todayIso()}
                    />
                  </Field>
                  <Field label="备注 / 外部党员核验依据" full>
                    <textarea name="note" rows={2} maxLength={2000} />
                  </Field>
                </>
              ) : modal.kind === "branch_committee_review" ? (
                <>
                  <Field label="审查日期" required>
                    <input
                      name="occurred_on"
                      type="date"
                      required
                      max={todayIso()}
                      defaultValue={todayIso()}
                    />
                  </Field>
                  <Field label="审查结论" required>
                    <select name="status" defaultValue="passed">
                      <option value="passed">通过</option>
                      <option value="in_progress">审查中</option>
                      <option value="failed">未通过</option>
                    </select>
                  </Field>
                  <Field label="参加人员" full>
                    <input
                      name="attendees"
                      maxLength={500}
                      placeholder="例如：支部书记、组织委员、宣传委员"
                    />
                  </Field>
                  <Field label="审查意见" full>
                    <textarea name="summary" rows={3} maxLength={4000} />
                  </Field>
                </>
              ) : modal.kind === "upper_pre_review" ? (
                <>
                  <Field label="预审日期" required>
                    <input
                      name="occurred_on"
                      type="date"
                      required
                      max={todayIso()}
                      defaultValue={todayIso()}
                    />
                  </Field>
                  <Field label="预审结论" required>
                    <select name="status" defaultValue="passed">
                      <option value="passed">通过</option>
                      <option value="in_progress">审查中</option>
                      <option value="supplement">需补充材料</option>
                      <option value="failed">未通过</option>
                    </select>
                  </Field>
                  <Field label="上级党组织" required>
                    <input
                      name="upper_org"
                      maxLength={200}
                      placeholder="例如：校党委、院系党委"
                    />
                  </Field>
                  <Field label="批复文号">
                    <input name="reply_no" maxLength={64} />
                  </Field>
                  <Field label="预审意见" full>
                    <textarea name="summary" rows={3} maxLength={4000} />
                  </Field>
                </>
              ) : modal.kind === "application_form" ? (
                <>
                  <Field label="填写日期" required>
                    <input
                      name="occurred_on"
                      type="date"
                      required
                      max={todayIso()}
                      defaultValue={todayIso()}
                    />
                  </Field>
                  <Field label="志愿书状态" required>
                    <select name="status" defaultValue="submitted">
                      <option value="draft">填写中</option>
                      <option value="submitted">已提交</option>
                      <option value="reviewed">已审核</option>
                    </select>
                  </Field>
                  <Field label="志愿书编号">
                    <input name="form_no" maxLength={64} />
                  </Field>
                  <Field label="审核日期">
                    <input
                      name="reviewed_on"
                      type="date"
                      max={todayIso()}
                    />
                  </Field>
                </>
              ) : modal.kind === "branch_vote" ? (
                <>
                  <Field label="票决日期" required>
                    <input
                      name="occurred_on"
                      type="date"
                      required
                      max={todayIso()}
                      defaultValue={todayIso()}
                    />
                  </Field>
                  <Field label="票决事项" required>
                    <select
                      name="meeting_for"
                      defaultValue={stage === "发展对象" ? "reception" : "conversion"}
                    >
                      {stage === "发展对象" ? (
                        <option value="reception">接收预备党员</option>
                      ) : (
                        <>
                          <option value="reception">接收预备党员（历史补录）</option>
                          <option value="conversion">预备党员转正</option>
                          <option value="disqualification">取消预备党员资格</option>
                        </>
                      )}
                    </select>
                  </Field>
                  <Field label="票决结果" required>
                    <select name="status" defaultValue="passed">
                      <option value="passed">通过</option>
                      <option value="not_passed">未通过</option>
                    </select>
                  </Field>
                  <Field label="应到人数" required>
                    <input name="eligible_count" type="number" min="0" max="10000" required />
                  </Field>
                  <Field label="实到人数" required>
                    <input name="attended_count" type="number" min="0" max="10000" required />
                  </Field>
                  <Field label="同意票数" required>
                    <input name="agree_count" type="number" min="0" max="10000" required />
                  </Field>
                  <Field label="不同意票数" required>
                    <input name="disagree_count" type="number" min="0" max="10000" required />
                  </Field>
                  <Field label="弃权票数" required>
                    <input name="abstain_count" type="number" min="0" max="10000" required />
                  </Field>
                  <Field label="票决结果和决议内容" required full>
                    <textarea name="summary" rows={4} required maxLength={4000} />
                  </Field>
                  <div className="inline-note field full">
                    系统只登记会议票数、结果和决议，不按票数自动判定通过；票决事项须与当前发展阶段相符。
                  </div>
                </>
              ) : modal.kind === "probation_outcome" ? (
                <>
                  <Field label="决定日期" required>
                    <input
                      name="occurred_on"
                      type="date"
                      required
                      max={todayIso()}
                      defaultValue={todayIso()}
                    />
                  </Field>
                  <Field label="转正结果" required>
                    <select name="status" defaultValue="qualified">
                      <option value="qualified">按期转正</option>
                      <option value="extended">延长预备期</option>
                      <option value="disqualified">取消预备党员资格</option>
                    </select>
                  </Field>
                  <Field label="延长预备期至">
                    <input name="effective_until" type="date" />
                    <small>仅“延长预备期”必填；须晚于决定日期，且晚于上一次延长截止日期。</small>
                  </Field>
                  <Field label="组织结论" required full>
                    <textarea name="summary" rows={4} required maxLength={4000} />
                  </Field>
                  <div className="inline-note field full">
                    延长预备期是独立记录，不改变发展阶段；取消预备党员资格须通过阶段流转进入终态。
                  </div>
                </>
              ) : modal.kind === "higher_record" ? (
                <>
                  <Field label="备案日期" required>
                    <input
                      name="occurred_on"
                      type="date"
                      required
                      max={todayIso()}
                      defaultValue={todayIso()}
                    />
                  </Field>
                  <Field label="上级党组织" required>
                    <input
                      name="upper_org"
                      maxLength={200}
                      required
                      placeholder="例如：校党委、院系党委"
                    />
                  </Field>
                  <Field label="批复文号">
                    <input name="reply_no" maxLength={64} />
                  </Field>
                  <Field label="备案说明" full>
                    <textarea name="summary" rows={3} maxLength={4000} />
                  </Field>
                  <div className="inline-note field full">
                    仅登记再上一级党委组织部门备案事实和批复要素，不替代上级党组织办理。
                  </div>
                </>
              ) : modal.kind === "party_group" ? (
                <>
                  <Field label="编入日期" required>
                    <input
                      name="occurred_on"
                      type="date"
                      required
                      max={todayIso()}
                      defaultValue={todayIso()}
                    />
                  </Field>
                  <Field label="党支部">
                    <input name="party_branch" maxLength={200} />
                  </Field>
                  <Field label="党小组" required>
                    <input name="party_group" maxLength={200} required />
                  </Field>
                  <Field label="编组说明" full>
                    <textarea name="summary" rows={3} maxLength={4000} />
                  </Field>
                  <div className="inline-note field full">
                    编入党支部和党小组由支部办理；系统只做轻量登记，不建立独立模块。
                  </div>
                </>
              ) : (
                <>
                  <Field label="谈话日期" required>
                    <input
                      name="occurred_on"
                      type="date"
                      required
                      max={todayIso()}
                      defaultValue={todayIso()}
                    />
                  </Field>
                  <Field label="谈话人" required>
                    <input name="talker" maxLength={100} />
                  </Field>
                  <Field label="谈话人所在组织">
                    <input name="talker_org" maxLength={200} />
                  </Field>
                  <Field label="谈话情况" full>
                    <textarea name="summary" rows={4} maxLength={4000} />
                  </Field>
                </>
              )}
              {!["contact", "introducer"].includes(modal.kind) && (
                <Field label="备注" full>
                  <textarea name="note" rows={2} maxLength={2000} />
                </Field>
              )}
              <Field label="登记依据" required full>
                <textarea name="reason" rows={3} required maxLength={2000} />
              </Field>
            </div>
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <button className="button primary" disabled={busy}>
                {busy ? "保存中…" : "保存登记"}
              </button>
            </div>
          </form>
        </Modal>
      )}
      {modal?.type === "check" && (
        <Modal title="材料核对结果" wide flat onClose={() => setModal(null)}>
          <p className="body-copy">{modal.note}</p>
          {modal.missing.length ? (
            <>
              <h3>需人工补充或核验</h3>
              <ul className="material-check-list">
                {modal.missing.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </>
          ) : (
            <div className="success-note">
              <CheckCircle size={20} />
              当前已登记清单无待核验项。
            </div>
          )}
        </Modal>
      )}
      {modal?.type === "review-material" && (
        <Modal title="登记材料核验结果" wide flat onClose={() => !busy && setModal(null)}>
          <h3>{modal.material.material_type}</h3>
          <form onSubmit={decideMaterial}>
            <div className="form-grid">
              <Field label="核验结果" full>
                <select name="review_status">
                  <option value="approved">核验通过</option>
                  <option value="rejected">退回补充</option>
                </select>
              </Field>
              <Field label="材料落款日期" full>
                <input
                  name="document_date"
                  type="date"
                  max={todayIso()}
                  defaultValue={modal.material.document_date || ""}
                />
                <small>
                  历史材料可在此按原件补录；入党申请书核验前必须有落款日期。
                </small>
              </Field>
              <Field label="核验依据与意见" required full>
                <textarea name="note" required maxLength={500} rows={4} />
              </Field>
            </div>
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <button className="button primary" disabled={busy}>
                保存核验结果
              </button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}
