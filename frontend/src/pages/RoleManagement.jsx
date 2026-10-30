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
function procedureStatusLabel(group) {
  if (!group?.current) return "未登记";
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
    }[group.current.status] || "待核对"
  );
}
function procedureTone(group) {
  if (!group?.current) return "blue";
  if (group.satisfied) return "green";
  return group.current.status === "failed" ? "red" : "orange";
}
function DevelopmentProcedurePanel({
  state,
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
  const canRegisterBranchProcedure = ["branch_secretary", "organizer"].includes(
    session.user.role,
  );
  const canRegisterUpperProcedure = ["school_admin", "department_admin"].includes(
    session.user.role,
  );
  const formalMembers = w.members.filter(
    (p) => p.stage === "正式党员" && p.id !== member?.id,
  );
  const procedureGaps = [
    !procedureState.contacts.satisfied && "培养联系人",
    !procedureState.introducers.satisfied && "入党介绍人",
    !procedureState.branch_committee_review.satisfied && "支委会审查",
    !procedureState.upper_pre_review.satisfied && "上级党委预审",
    !procedureState.application_form.satisfied && "入党志愿书",
  ].filter(Boolean);
  const politicalMaterials = developmentMaterials.filter(
    (m) => m.material_type === "政治审查材料" && m.review_status === "approved",
  );
  const trainingMaterials = developmentMaterials.filter(
    (m) => m.material_type === "党课培训证明" && m.review_status === "approved",
  );
  const canRegisterGates = ["发展对象", "预备党员", "正式党员"].includes(stage);
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
              { contact: "培养联系人", introducer: "入党介绍人" }[kind] ||
              "",
            status:
              kind === "contact"
                ? "assigned"
                : kind === "introducer"
                  ? "confirmed"
                  : kind === "upper_talk"
                    ? "completed"
                    : status,
            id: crypto.randomUUID(),
            created_at: new Date().toISOString(),
            created_by: session.user.name,
            data_level: [
              "branch_committee_review",
              "upper_pre_review",
              "upper_talk",
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
                <Badge tone={p.stage === "正式党员" ? "green" : "orange"}>
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
          {member ? (
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
                items={["材料清单", "培养记录", "发展程序", "阶段流转"]}
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
                  <div className="sub-toolbar">
                    <span>阶段变更由组织人员人工办理</span>
                    <button
                      className="button primary"
                      disabled={!detail || busy || STAGES.indexOf(stage) === 4}
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
                      {STAGES.filter(
                        (s, i) => i === STAGES.indexOf(stage) + 1,
                      ).map((s) => (
                        <option key={s}>{s}</option>
                      ))}
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
                                !procedureState.upper_talk.satisfied
                                  ? "程序提示：上级党委派人谈话尚未登记，应在上级审批前完成。"
                                  : ""
                              }`
                            : "此操作登记人工决定，不能替代支部讨论、上级审批或其他应履行程序。"}
                  </div>
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
