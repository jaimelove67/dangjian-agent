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
  newAudit,
  getDemoDevelopment,
} from "../role-data";
import { getDemoFile } from "../demo-files";
import {
  reviewDemoMeeting,
  transitionDemoMember,
  linkDemoAccount,
} from "../role-actions";
import { STAGES } from "../data";
import { STAGE_LABELS } from "../contracts";
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
        <Modal title="查阅个人材料" wide onClose={() => setDetail(null)}>
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
        <Modal title="核对并审核" wide onClose={() => !busy && setDetail(null)}>
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
  const materialDraft = useMaterialDraft({ material_type: "" });
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
  const stage = IS_LIVE
    ? STAGE_LABELS[detail?.current_stage] || member?.stage
    : member?.stage;
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
      if (modal === "link") {
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
          submit_date: f.get("submit_date") || null,
          reason,
        };
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
            modal === "link"
              ? "明确关联本人档案账号"
              : modal === "transition"
                ? "人工登记发展阶段"
                : modal === "material"
                  ? "登记发展材料"
                  : "登记培养记录",
            "member_profile",
            member.id,
          ),
          ...prev,
        ]);
      setModal(null);
      setTick((t) => t + 1);
      notify("办理记录已保存");
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
          missing: materials
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
        review_status = f.get("review_status");
      if (!note) throw new Error("请填写核验意见。");
      if (IS_LIVE)
        await roleApi.reviewMaterial(modal.material.id, {
          review_status,
          note,
          reason: note,
        });
      else {
        saveDemoProfile({
          ...detail,
          materials: materials.map((m) =>
            m.id === modal.material.id ? { ...m, review_status, note } : m,
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
              <Tabs
                items={["材料清单", "培养记录", "阶段流转"]}
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
                        {materials.map((m, i) => (
                          <tr key={m.id || i}>
                            <td>{m.material_type}</td>
                            <td>
                              {m.file_version || "—"}
                              <small className="cell-subtext">
                                {m.submit_date || "未登记"}
                              </small>
                            </td>
                            <td>
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
                            </td>
                            <td>
                              <button
                                className="text-button link"
                                disabled={!m.id}
                                onClick={() => reviewMaterial(m)}
                              >
                                核验
                              </button>
                              {IS_LIVE && m.has_file && <button type="button" className="text-button link separated-action" onClick={async () => {
                                try { downloadBlob(await roleApi.developmentFile(m.id), m.file_name || `${m.material_type}.bin`); }
                                catch (e) { notify(e.message, "error"); }
                              }}>下载原件</button>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!materials.length && <Empty title="暂无登记材料" />}
                  </div>
                  <button
                    className="work-guidance-link"
                    onClick={() => navigate("inbox", { profileId: member.id })}
                  >
                    查看本人提交的私有原件
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
            modal === "link"
              ? "明确关联登录账号"
              : modal === "material"
                ? "登记发展材料"
                : modal === "cultivation"
                  ? "登记培养记录"
                  : "人工登记阶段变更"
          }
          wide
          flat
          onClose={() => !busy && setModal(null)}
        >
          <form onSubmit={save}>
            <div className="form-grid">
              {modal === "link" ? (
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
                  <Field label="组织收到日期">
                    <input
                      name="submit_date"
                      type="date"
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
                    此操作登记人工决定，不能替代支部讨论、上级审批或其他应履行程序。
                  </div>
                </>
              )}
            </div>
            {modal === "material" && <MaterialSuggestions file={materialDraft.file} profileId={member.id} disabled={busy} onApply={(fields) => materialDraft.apply(fields, ["material_type"])} />}
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
      {modal?.type === "check" && (
        <Modal title="材料核对结果" onClose={() => setModal(null)}>
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
        <Modal title="登记材料核验结果" onClose={() => !busy && setModal(null)}>
          <h3>{modal.material.material_type}</h3>
          <form onSubmit={decideMaterial}>
            <div className="form-grid">
              <Field label="核验结果" full>
                <select name="review_status">
                  <option value="approved">核验通过</option>
                  <option value="rejected">退回补充</option>
                </select>
              </Field>
              <Field label="核验依据与意见" required full>
                <textarea name="note" required maxLength={2000} rows={4} />
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
