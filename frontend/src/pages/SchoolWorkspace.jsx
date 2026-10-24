import { useMemo, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Bell,
  BookOpen,
  CalendarBlank,
  CheckCircle,
  ClipboardText,
  DownloadSimple,
  FileText,
  GraduationCap,
  Plus,
  ShieldCheck,
  TreeStructure,
  UsersThree,
  WarningCircle,
  Clock,
} from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE } from "../api";
import { branchOrganizations } from "../contracts";
import { useManagedWorkspace } from "../role-hooks";
import { hasPermission, roleLabel } from "../roles";
import { newAudit } from "../role-data";
import { reviewDemoMeeting } from "../role-actions";
import { STAGES, notices } from "../data";
import {
  BUSINESS_TYPES,
  SCHOOL_YEAR,
  decideSchoolRecord,
  filterSchoolRecords,
  formatSchoolTime,
  isSchoolComplete,
  isSchoolOverdue,
  schoolMeetingRecords,
  schoolToday,
} from "../school-data";
import {
  Badge,
  Empty,
  ErrorBox,
  Field,
  Loading,
  Modal,
  PageHeader,
  PanelTitle,
  SearchInput,
  Select,
  Tabs,
  exportCsv,
} from "../components";

function useSchoolWorkspace() {
  const w = useManagedWorkspace();
  const { session } = useApp();
  const { data } = useStore();
  const records = useMemo(
    () => [
      ...schoolMeetingRecords(w.meetings, w.orgs),
      ...(!IS_LIVE
        ? (data.schoolWorkItems || []).filter(
            (r) => (r.tenant_id || "school-1") === session.user.tenant_id,
          )
        : []),
    ],
    [w.meetings, w.orgs, data.schoolWorkItems, session.user.tenant_id],
  );
  return { ...w, records };
}
function useSchoolFilters(defaults = {}) {
  const { routeParams } = useApp();
  const { data } = useStore();
  return useState({
    year: !IS_LIVE ? data.schoolRules?.year || SCHOOL_YEAR : SCHOOL_YEAR,
    department: "",
    orgId: "",
    business: "",
    stage: "",
    status: "",
    query: "",
    ...defaults,
    ...routeParams,
  });
}
function SchoolFilters({
  filters,
  setFilters,
  orgs,
  business = false,
  stage = false,
  status = true,
}) {
  const set = (key, value) =>
    setFilters((prev) => ({
      ...prev,
      [key]: value,
      ...(key === "department" ? { orgId: "" } : {}),
    }));
  return (
    <div className="school-filters">
      <Select
        label="业务年度"
        value={filters.year}
        onChange={(e) => set("year", e.target.value)}
      >
        <option value="">全部年度</option>
        <option>2026</option>
        <option>2025</option>
      </Select>
      <Select
        label="所属院系"
        value={filters.department}
        onChange={(e) => set("department", e.target.value)}
      >
        <option value="">全部院系</option>
        {[...new Set(orgs.map((o) => o.department).filter(Boolean))].map(
          (d) => (
            <option key={d}>{d}</option>
          ),
        )}
      </Select>
      <Select
        label="所属支部"
        value={filters.orgId}
        onChange={(e) => set("orgId", e.target.value)}
      >
        <option value="">全部支部</option>
        {branchOrganizations(orgs)
          .filter(
            (o) => !filters.department || o.department === filters.department,
          )
          .map((o) => (
            <option value={o.id} key={o.id}>
              {o.name}
            </option>
          ))}
      </Select>
      {business && (
        <Select
          label="业务类型"
          value={filters.business}
          onChange={(e) => set("business", e.target.value)}
        >
          <option value="">全部业务</option>
          {BUSINESS_TYPES.map((b) => (
            <option key={b}>{b}</option>
          ))}
        </Select>
      )}
      {stage && (
        <Select
          label="发展阶段"
          value={filters.stage}
          onChange={(e) => set("stage", e.target.value)}
        >
          <option value="">全部发展阶段</option>
          {STAGES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </Select>
      )}
      {status && (
        <Select
          label="办理状态"
          value={filters.status}
          onChange={(e) => set("status", e.target.value)}
        >
          <option value="">全部状态</option>
          {["待审核", "待补充", "待提交", "逾期", "待归档", "已归档"].map(
            (s) => (
              <option key={s}>{s}</option>
            ),
          )}
        </Select>
      )}
    </div>
  );
}
function RecordStatus({ record }) {
  return (
    <div className="school-record-status">
      <Badge
        tone={
          record.status === "待审核"
            ? "orange"
            : isSchoolComplete(record)
              ? "green"
              : ["待补充", "已退回"].includes(record.status)
                ? "red"
                : "blue"
        }
      >
        {record.status}
      </Badge>
      {isSchoolOverdue(record) && <span className="school-overdue">逾期</span>}
    </div>
  );
}
function RecordsTable({ records, open, compact = false }) {
  const [page, setPage] = useState(1);
  const pageSize = 8;
  const currentPage = Math.min(
    page,
    Math.max(1, Math.ceil(records.length / pageSize)),
  );
  const visible = compact
    ? records.slice(0, 4)
    : records.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  return (
    <>
      <div className="table-scroll school-table">
        <table>
          <thead>
            <tr>
              <th>事项 / 所属组织</th>
              {!compact && <th>业务类型</th>}
              <th>提交人 / 版本</th>
              <th>办理状态</th>
              {!compact && <th>截止日期</th>}
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r) => (
              <tr key={r.id}>
                <td>
                  <button
                    className="school-record-title school-record-open"
                    onClick={() => open(r)}
                  >
                    {r.title}
                  </button>
                  <small className="cell-subtext">
                    {r.organization}
                    {r.person ? ` · ${r.person}` : ""}
                  </small>
                </td>
                {!compact && (
                  <td>
                    {r.business}
                    <small className="cell-subtext">
                      {r.stage || r.reviewLevel || "学校统筹"}
                    </small>
                  </td>
                )}
                <td>
                  {r.submittedName || "待提交"}
                  <small className="cell-subtext">
                    v{r.revision} · {r.year}年度
                  </small>
                </td>
                <td>
                  <RecordStatus record={r} />
                </td>
                {!compact && <td className="numeric">{r.dueDate || "—"}</td>}
                <td>
                  <button className="text-button link" onClick={() => open(r)}>
                    {r.status === "待审核"
                      ? "核对并审核"
                      : r.status === "已通过"
                        ? "确认归档"
                        : "查看事项"}
                    <ArrowUpRight size={13} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!records.length && (
        <Empty
          title="暂无符合条件的事项"
          description="可调整院系、支部、年度或办理状态后查看。"
        />
      )}
      {!compact && records.length > pageSize && (
        <div className="school-pagination">
          <span>共 {records.length} 项</span>
          <button
            className="button secondary"
            disabled={currentPage === 1}
            onClick={() => setPage(currentPage - 1)}
          >
            上一页
          </button>
          <span>
            {currentPage} / {Math.ceil(records.length / pageSize)}
          </span>
          <button
            className="button secondary"
            disabled={currentPage * pageSize >= records.length}
            onClick={() => setPage(currentPage + 1)}
          >
            下一页
          </button>
        </div>
      )}
    </>
  );
}

function RecordModal({ record, onClose }) {
  const { session, navigate } = useApp();
  const { data, update, notify } = useStore();
  const [tab, setTab] = useState("材料核对");
  const [opinion, setOpinion] = useState("");
  const [decision, setDecision] = useState("approve");
  const [error, setError] = useState(null);
  const [material, setMaterial] = useState(null);
  const pending = record.status === "待审核";
  const archive = record.status === "已通过";
  const self = record.submittedBy === session.user.id;
  const allowed = hasPermission(
    session,
    archive ? "admin.archive_confirm" : "admin.review",
  );
  const history = [...(record.history || [])].reverse();
  function handle(e) {
    e.preventDefault();
    setError(null);
    try {
      if (IS_LIVE) throw new Error("请进入原业务页面按当前授权办理。");
      if (!allowed) throw new Error("当前账号没有此项办理权限。");
      const action = archive ? "archive" : decision;
      if (record.source === "meeting") {
        const current = data.meetings.find((m) => m.id === record.id);
        let next;
        if (archive) {
          if (
            !current ||
            current.revision !== record.revision ||
            current.status !== "已完成" ||
            current.review_status !== "approved"
          )
            throw new Error("须先通过独立人工审核，并核对当前版本后归档。");
          if (!opinion.trim()) throw new Error("请填写归档确认意见。");
          next = {
            ...current,
            status: "已归档",
            archived_at: new Date().toISOString(),
            archived_by: session.user.id,
            archived_name: session.user.name,
            revision: current.revision + 1,
          };
        } else
          next = reviewDemoMeeting(
            session,
            current,
            record.revision,
            action === "approve" ? "approved" : "rejected",
            opinion,
          );
        next.schoolHistory = [
          ...record.history,
          {
            id: crypto.randomUUID(),
            action: archive
              ? "学校确认归档"
              : action === "approve"
                ? "学校审核通过"
                : "退回补充",
            actor: session.user.name,
            at: new Date().toISOString(),
            version: next.revision,
            opinion: opinion.trim(),
          },
        ];
        update("meetings", (prev) =>
          prev.map((m) => (m.id === record.id ? next : m)),
        );
      } else {
        const current = data.schoolWorkItems.find((r) => r.id === record.id);
        const next = decideSchoolRecord(
          session,
          current,
          record.revision,
          action,
          opinion,
        );
        update("schoolWorkItems", (prev) =>
          prev.map((r) => (r.id === record.id ? next : r)),
        );
      }
      update("auditEntries", (prev) => [
        newAudit(
          session.user,
          archive
            ? "校级确认归档"
            : decision === "approve"
              ? "校级审核通过"
              : "校级退回补充",
          record.business,
          record.id,
        ),
        ...prev,
      ]);
      notify(
        archive
          ? "归档确认已保存，可在办理记录中追溯"
          : decision === "approve"
            ? "审核意见已保存，事项进入待归档"
            : "退回意见已保存，事项进入待补充",
      );
      onClose();
    } catch (err) {
      setError(err);
    }
  }
  function remind() {
    if (IS_LIVE) {
      notify("当前业务请在原业务页面登记督办", "error");
      return;
    }
    const entry = {
      id: crypto.randomUUID(),
      recordId: record.id,
      title: record.title,
      organization: record.organization,
      actor: session.user.name,
      at: new Date().toISOString(),
    };
    update("schoolReminders", (prev) => [entry, ...(prev || [])]);
    update("auditEntries", (prev) => [
      newAudit(session.user, "登记校级督办", record.business, record.id),
      ...prev,
    ]);
    notify("本地督办记录已保存");
  }
  return (
    <Modal title="校级业务办理" wide flat onClose={onClose}>
      <div className="school-record-heading">
        <Badge tone="red">{record.business}</Badge>
        <RecordStatus record={record} />
        <h2>{record.title}</h2>
        <p>{record.organization}</p>
      </div>
      <dl className="school-record-meta">
        <div>
          <dt>提交人</dt>
          <dd>{record.submittedName || "待提交"}</dd>
        </div>
        <div>
          <dt>学校审核人</dt>
          <dd>
            {record.reviewedBy ||
              (record.reviewed_by
                ? data.accounts.find((a) => a.id === record.reviewed_by)
                    ?.name || record.reviewed_by
                : isSchoolComplete(record)
                  ? "历史记录未登记"
                  : "待学校办理")}
          </dd>
        </div>
        <div>
          <dt>当前版本</dt>
          <dd>v{record.revision}</dd>
        </div>
        <div>
          <dt>适用年度</dt>
          <dd>{record.year}年度</dd>
        </div>
        <div>
          <dt>截止日期</dt>
          <dd>{record.dueDate || "—"}</dd>
        </div>
        <div>
          <dt>归档状态</dt>
          <dd>{record.archived ? "已确认归档" : "待确认"}</dd>
        </div>
        {record.archivedBy && (
          <div>
            <dt>归档确认人</dt>
            <dd>{record.archivedBy}</dd>
          </div>
        )}
      </dl>
      <Tabs
        items={["材料核对", "办理记录与版本"]}
        active={tab}
        onChange={setTab}
      />
      {tab === "材料核对" ? (
        <div className="school-material-list">
          {record.materials.map((m) => (
            <div className="school-material" key={m.name}>
              <FileText size={22} />
              <div>
                <h3>{m.name}</h3>
                <p>
                  {m.version} · {m.complete ? "已登记" : "缺少材料"}
                </p>
              </div>
              <button
                className="text-button link"
                onClick={() => setMaterial(material === m.name ? null : m.name)}
              >
                {material === m.name ? "收起摘要" : "查看摘要"}
              </button>
              {material === m.name && (
                <p className="school-material-content">{m.content}</p>
              )}
            </div>
          ))}
          {!IS_LIVE && record.business === "党员发展" && (
            <p className="school-muted-note">
              学校材料要求：{data.schoolRules?.developmentMaterials}
            </p>
          )}
          {archive && !IS_LIVE && (
            <p className="school-muted-note">
              归档要求：{data.schoolRules?.archiveRequirements}
            </p>
          )}
          <p className="school-muted-note">
            请核对材料内容及版本；未附原件时，请先补齐后再审核。
          </p>
        </div>
      ) : (
        <div className="school-history">
          {history.map((h) => (
            <div key={h.id}>
              <CheckCircle size={18} />
              <div>
                <strong>
                  {h.action}
                  <small>v{h.version}</small>
                </strong>
                <p>
                  {h.actor} · {formatSchoolTime(h.at)}
                </p>
                <div>{h.opinion}</div>
              </div>
            </div>
          ))}
          {!history.length && <Empty title="暂无办理记录" />}
        </div>
      )}
      {(pending || archive) && (
        <form className="school-review-form" onSubmit={handle}>
          <h3>{archive ? "归档确认" : "学校审核意见"}</h3>
          {pending && (
            <div className="review-decision">
              <label>
                <input
                  type="radio"
                  name="school-decision"
                  checked={decision === "approve"}
                  onChange={() => setDecision("approve")}
                />
                审核通过
              </label>
              <label>
                <input
                  type="radio"
                  name="school-decision"
                  checked={decision === "return"}
                  onChange={() => setDecision("return")}
                />
                退回补充
              </label>
            </div>
          )}
          <Field label={archive ? "归档确认依据" : "处理意见与依据"} required>
            <textarea
              name="opinion"
              value={opinion}
              onChange={(e) => setOpinion(e.target.value)}
              rows={3}
              maxLength={2000}
              required
              placeholder={
                archive
                  ? "请确认材料、审核结果及归档要求"
                  : "请写明核对依据；退回时注明需补充的材料"
              }
            />
          </Field>
          {self && pending && (
            <p className="school-warning">提交人须由另一位授权人员独立审核。</p>
          )}
          {error && <ErrorBox error={error} />}
          <div className="modal-actions">
            <button
              type="button"
              className="button secondary"
              onClick={onClose}
            >
              取消
            </button>
            <button
              className="button primary"
              disabled={IS_LIVE || !allowed || (self && pending)}
            >
              {archive ? "确认归档" : "保存审核意见"}
            </button>
          </div>
        </form>
      )}
      <div className="school-record-links">
        <button
          className="text-button link"
          onClick={() => {
            onClose();
            navigate(
              record.business === "党员发展"
                ? "development"
                : record.source === "meeting"
                  ? "meetings"
                  : record.business === "学习教育"
                    ? "school-learning"
                    : record.business === "年度考核"
                      ? "assessment"
                      : "school-life",
              {
                ...(record.profileId ? { profileId: record.profileId } : {}),
                ...(record.source === "meeting" ? { id: record.id } : {}),
                ...(record.source !== "meeting" && !record.profileId
                  ? { recordId: record.id, year: record.year }
                  : {}),
              },
            );
          }}
        >
          进入对应业务
          <ArrowRight size={14} />
        </button>
        {!isSchoolComplete(record) && (
          <button className="button secondary" onClick={remind}>
            <Bell size={15} />
            记录督办
          </button>
        )}
      </div>
      {!!data.schoolReminders?.filter((r) => r.recordId === record.id)
        .length && (
        <p className="school-muted-note">
          已记录督办{" "}
          {data.schoolReminders.filter((r) => r.recordId === record.id).length}{" "}
          次，可在校内操作审计中查询。
        </p>
      )}
    </Modal>
  );
}

function WorkspaceState({ w }) {
  return (
    <>
      {w.loading && <Loading />}
      {w.error && <ErrorBox error={w.error} retry={w.reload} />}
      {IS_LIVE && (
        <p className="school-muted-note">
          当前概览仅统计已加载的授权记录。新增校级计划与规则的保存需接入对应业务服务。
        </p>
      )}
    </>
  );
}

function ProgressTable({
  records,
  orgs,
  department,
  orgId,
  onDetail,
  full = false,
}) {
  const branches = branchOrganizations(orgs);
  const departments = [...new Set(branches.map((org) => org.department).filter(Boolean))];
  const rows = orgId
    ? branches
        .filter((o) => o.id === orgId)
        .map((o) => ({
          id: o.id,
          label: o.name,
          department: o.department,
          orgId: o.id,
        }))
    : department
      ? branches
          .filter((o) => o.department === department)
          .map((o) => ({ id: o.id, label: o.name, department, orgId: o.id }))
      : departments.length ? departments.map(
          (d) => ({ id: d, label: d, department: d }),
        ) : branches.map((org) => ({ id: org.id, label: org.name, orgId: org.id }));
  return (
    <div className="table-scroll school-table">
      <table>
        <thead>
          <tr>
            <th>{department || orgId || !departments.length ? "党支部" : "院系"}</th>
            <th>登记事项</th>
            <th>待审核</th>
            <th>逾期</th>
            <th>已通过 / 归档</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {(full ? rows : rows.slice(0, 5)).map((row) => {
            const items = records.filter((r) =>
              row.orgId
                ? r.orgId === row.orgId
                : r.department === row.department,
            );
            return (
              <tr key={row.id}>
                <td>
                  <strong className="school-record-title">{row.label}</strong>
                </td>
                <td>{items.length || "—"}</td>
                <td>{items.filter((r) => r.status === "待审核").length}</td>
                <td>
                  <span
                    className={
                      items.some((item) => isSchoolOverdue(item))
                        ? "school-overdue"
                        : ""
                    }
                  >
                    {items.filter((r) => isSchoolOverdue(r)).length}
                  </span>
                </td>
                <td>
                  {items.filter(isSchoolComplete).length} / {items.length}
                  <small className="cell-subtext">
                    {items.length
                      ? `${Math.round((items.filter(isSchoolComplete).length / items.length) * 100)}% 已处理`
                      : "暂无登记事项"}
                  </small>
                </td>
                <td>
                  <button
                    className="text-button link"
                    onClick={() => onDetail(row)}
                  >
                    查看明细
                    <ArrowUpRight size={13} />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!rows.length && <Empty title="暂无授权组织" />}
    </div>
  );
}

export function SchoolDashboard() {
  const { session, navigate } = useApp();
  const w = useSchoolWorkspace();
  const [filters, setFilters] = useSchoolFilters();
  const [detail, setDetail] = useState(null);
  const [notice, setNotice] = useState(null);
  const records = filterSchoolRecords(w.records, filters);
  const pending = records.filter((r) => r.status === "待审核");
  const overdue = records.filter((r) => isSchoolOverdue(r));
  const missing = records.filter((r) =>
    ["待补充", "已退回"].includes(r.status),
  );
  const orgs = w.orgs.filter(
    (o) =>
      (!filters.department || o.department === filters.department) &&
      (!filters.orgId || o.id === filters.orgId),
  );
  const members = w.members.filter(
    (m) =>
      ["正式党员", "预备党员"].includes(m.stage) &&
      (!filters.department || m.department === filters.department) &&
      (!filters.orgId || m.orgId === filters.orgId),
  );
  const metrics = [
    [
      "在册党员",
      members.length.toLocaleString(),
      "人",
      UsersThree,
      "members",
      "",
      "名册与组织归属",
    ],
    [
      "基层党支部",
      branchOrganizations(orgs).length,
      "个",
      TreeStructure,
      "organization",
      "",
      "组织与负责人",
    ],
    [
      "待学校审核",
      pending.length,
      "项",
      ClipboardText,
      "reviews",
      "待审核",
      "集中核对与处理",
    ],
    [
      "逾期未办",
      overdue.length,
      "项",
      Clock,
      "school-supervision",
      "逾期",
      "定位组织与责任人",
    ],
    [
      "材料待补",
      missing.length,
      "项",
      FileText,
      "school-supervision",
      "待补充",
      "跟进补充与重提",
    ],
  ];
  return (
    <div className="school-workspace">
      <div className="school-heading">
        <div>
          <h1>学校工作台</h1>
          <p>{session.user.name}，欢迎回来。统筹全校工作，跟进每一项待办。</p>
        </div>
        <span className="school-scope">
          <ShieldCheck size={16} />
          全校业务范围<span>{IS_LIVE ? "业务环境" : "业务记录"}</span>
        </span>
      </div>
      <SchoolFilters
        filters={filters}
        setFilters={setFilters}
        orgs={w.orgs}
        status={false}
      />
      <WorkspaceState w={w} />
      <div className="school-metrics">
        {metrics.map(([label, value, unit, Icon, route, status, desc]) => (
          <button
            key={label}
            onClick={() =>
              navigate(route, {
                year: filters.year,
                department: filters.department,
                orgId: filters.orgId,
                ...(["members", "organization"].includes(route)
                  ? {
                      organization: filters.orgId
                        ? orgs[0]?.name
                        : filters.department,
                    }
                  : {}),
                ...(status ? { status } : {}),
              })
            }
          >
            <div>
              <span>{label}</span>
              <Icon size={19} />
            </div>
            <strong>
              {value}
              <small>{unit}</small>
            </strong>
            <p>
              {desc}
              <ArrowUpRight size={13} />
            </p>
          </button>
        ))}
      </div>
      <div className="school-main-grid">
        <section className="panel school-review-panel">
          <PanelTitle
            title="待学校审核"
            action="进入审核工作台"
            onAction={() => navigate("reviews", filters)}
          >
            <span className="school-count">{pending.length}</span>
          </PanelTitle>
          <p className="school-panel-description">
            院系核验后提交，按学校制度逐项审核并保留意见。
          </p>
          <RecordsTable records={pending} open={setDetail} compact />
        </section>
        <section className="panel school-attention">
          <PanelTitle title="需要关注" />
          <div className="school-attention-summary">
            <WarningCircle size={19} />
            <span>
              {overdue.length} 项逾期，{missing.length} 项材料待补
            </span>
          </div>
          {[
            ...overdue,
            ...missing.filter((r) => !overdue.some((o) => o.id === r.id)),
          ]
            .slice(0, 3)
            .map((r) => (
              <button
                className="school-issue"
                key={r.id}
                onClick={() => setDetail(r)}
              >
                <div>
                  <Badge tone={isSchoolOverdue(r) ? "red" : "orange"}>
                    {isSchoolOverdue(r) ? "逾期未办" : "材料待补"}
                  </Badge>
                  <span>{r.dueDate.slice(5)}</span>
                </div>
                <h3>{r.title}</h3>
                <p>{r.organization}</p>
              </button>
            ))}
          {!overdue.length && !missing.length && (
            <Empty
              title="当前无异常提醒"
              description="继续按计划跟进各项工作。"
            />
          )}
          <button
            className="school-panel-link"
            onClick={() => navigate("school-supervision", filters)}
          >
            查看全部问题与督办
            <ArrowRight size={15} />
          </button>
        </section>
      </div>
      <div className="school-bottom-grid">
        <section className="panel">
          <PanelTitle
            title="院系与支部工作进度"
            action="全校统计"
            onAction={() => navigate("analytics", filters)}
          />
          <p className="school-panel-description">
            按登记事项统计；选择院系后，可继续查看所属支部。
          </p>
          <ProgressTable
            records={records}
            orgs={w.orgs}
            department={filters.department}
            orgId={filters.orgId}
            onDetail={(row) =>
              navigate("school-supervision", { ...filters, ...row, status: "" })
            }
          />
        </section>
        <section className="panel school-notices">
          <PanelTitle
            title="重要通知"
            action="全部通知"
            onAction={() => navigate("school-notices")}
          />
          {!IS_LIVE ? (
            notices.slice(0, 4).map((n) => (
              <button
                className="school-notice"
                key={n.id}
                onClick={() => setNotice(n)}
              >
                <span>{n.date}</span>
                <div>
                  <h3>{n.title}</h3>
                  <small>{n.type}</small>
                </div>
              </button>
            ))
          ) : (
            <Empty
              title="暂无已加载通知"
              description="请以学校正式通知为准。"
            />
          )}
          <div className="school-duty-note">
            <ShieldCheck size={18} />
            <p>
              支部登记 · 院系核验督办
              <br />
              <strong>学校统筹、审核与确认</strong>
            </p>
          </div>
        </section>
      </div>
      {detail && (
        <RecordModal record={detail} onClose={() => setDetail(null)} />
      )}
      {notice && (
        <Modal title="学校通知" onClose={() => setNotice(null)}>
          <h2>{notice.title}</h2>
          <p className="body-copy">{notice.body}</p>
          <p className="school-muted-note">
            {notice.type} · {notice.date}
          </p>
        </Modal>
      )}
    </div>
  );
}

export function SchoolRecordsPage({ mode = "supervision" }) {
  const { routeParams, navigate } = useApp();
  const w = useSchoolWorkspace();
  const config = {
    supervision: [
      "问题与督办",
      "定位未完成、材料待补和逾期事项，持续跟进办理过程",
      "",
    ],
    reviews: ["集中审核", "集中核对材料与来源版本，按学校制度填写处理意见", ""],
    life: [
      "组织生活检查",
      "掌握三会一课、主题党日开展情况，审核后独立确认归档",
      "组织生活",
    ],
    learning: [
      "全校学习计划与任务",
      "统筹年度学习安排，跟进院系、支部完成情况",
      "学习教育",
    ],
    assessment: [
      "年度指标与组织考核",
      "维护学校年度考核指标，核对佐证并人工确认结果",
      "年度考核",
    ],
  }[mode];
  const [filters, setFilters] = useSchoolFilters({
    business: config[2],
    status: mode === "reviews" ? "待审核" : "",
  });
  const [tab, setTab] = useState(
    mode === "assessment"
      ? "组织考核"
      : mode === "learning"
        ? "学习计划"
        : "业务事项",
  );
  const [detail, setDetail] = useState(
    () => w.records.find((r) => r.id === routeParams.recordId) || null,
  );
  const [exportError, setExportError] = useState(null);
  const records = filterSchoolRecords(w.records, {
    ...filters,
    ...(config[2] ? { business: config[2] } : {}),
  });
  const tabs =
    mode === "assessment"
      ? ["组织考核", "年度指标", "佐证与确认"]
      : mode === "learning"
        ? ["学习计划", "完成情况与审核"]
        : mode === "life"
          ? ["业务事项", "待归档"]
          : ["业务事项", "办理记录"];
  const shown =
    tab === "办理记录"
      ? records.filter(
          (r) =>
            r.history.length > 1 ||
            isSchoolComplete(r) ||
            r.status === "待补充" ||
            r.status === "已退回",
        )
      : tab === "待归档"
        ? records.filter((r) => r.status === "已通过")
        : records;
  function exportRows() {
    try {
      exportCsv(
        [
          ["年度", "院系", "支部", "业务", "事项", "状态", "截止日期", "版本"],
          ...shown.map((r) => [
            r.year,
            r.department,
            r.organization,
            r.business,
            r.title,
            r.status,
            r.dueDate,
            r.revision,
          ]),
        ],
        `${config[0]}-${filters.year || "全部年度"}.csv`,
      );
    } catch (error) {
      setExportError(error);
    }
  }
  return (
    <div className="school-workspace">
      <PageHeader
        title={config[0]}
        subtitle={config[1]}
        action={
          <button className="button secondary" onClick={exportRows}>
            <DownloadSimple size={16} />
            导出当前清单
          </button>
        }
      />
      <WorkspaceState w={w} />
      <section className="panel school-business-panel">
        <Tabs
          items={tabs}
          active={tab}
          onChange={(t) => {
            setTab(t);
            if (t === "办理记录") setFilters((f) => ({ ...f, status: "" }));
          }}
        />
        {tab === "年度指标" ? (
          <SchoolIndicators year={filters.year} />
        ) : tab === "学习计划" ? (
          <SchoolLearningPlans />
        ) : (
          <>
            <SchoolFilters
              filters={filters}
              setFilters={setFilters}
              orgs={w.orgs}
              business={!config[2]}
            />
            <div className="school-list-toolbar">
              <SearchInput
                value={filters.query}
                placeholder="搜索事项、组织或提交人"
                onChange={(e) =>
                  setFilters((f) => ({ ...f, query: e.target.value }))
                }
              />
              <span>
                共 {shown.length} 项 ·{" "}
                {shown.filter((r) => isSchoolOverdue(r)).length} 项逾期
              </span>
            </div>
            {mode === "assessment" && (
              <div className="school-inline-guidance">
                院系与支部提交佐证，学校核对来源版本后人工确认考核结果。
                <button
                  className="text-button link"
                  onClick={() =>
                    navigate("analytics", { ...filters, business: "年度考核" })
                  }
                >
                  查看组织统计
                  <ArrowRight size={13} />
                </button>
              </div>
            )}
            {exportError && <ErrorBox error={exportError} />}
            <RecordsTable records={shown} open={setDetail} />
          </>
        )}
      </section>
      {detail && (
        <RecordModal record={detail} onClose={() => setDetail(null)} />
      )}
    </div>
  );
}

export function SchoolDevelopment() {
  const { navigate } = useApp();
  const { data } = useStore();
  const w = useSchoolWorkspace();
  const [filters, setFilters] = useSchoolFilters({ business: "党员发展" });
  const [tab, setTab] = useState("人员与阶段");
  const [detail, setDetail] = useState(null);
  const [page, setPage] = useState(1);
  const people = w.members.filter(
    (m) =>
      (!filters.department || m.department === filters.department) &&
      (!filters.orgId || m.orgId === filters.orgId) &&
      (!filters.stage || m.stage === filters.stage) &&
      (!filters.year || String(m.year || SCHOOL_YEAR) === filters.year) &&
      (!filters.query || `${m.name} ${m.number}`.includes(filters.query)),
  );
  const pageCount = Math.max(1, Math.ceil(people.length / 10));
  const currentPage = Math.min(page, pageCount);
  const records = filterSchoolRecords(w.records, {
    ...filters,
    business: "党员发展",
  });
  return (
    <div className="school-workspace">
      <PageHeader
        title="全校党员发展进度"
        subtitle="按发展阶段查看人员，进入档案核对材料、培养记录和学校审核事项"
      />
      <WorkspaceState w={w} />
      <section className="panel school-business-panel">
        <SchoolFilters
          filters={filters}
          setFilters={(f) => {
            setFilters(f);
            setPage(1);
          }}
          orgs={w.orgs}
          stage
          status={false}
        />
        <div className="school-stage-overview">
          {STAGES.map((stage) => (
            <button
              key={stage}
              className={filters.stage === stage ? "active" : ""}
              onClick={() => {
                setFilters((f) => ({
                  ...f,
                  stage: f.stage === stage ? "" : stage,
                }));
                setPage(1);
              }}
            >
              <GraduationCap size={19} />
              <span>{stage}</span>
              <strong>
                {
                  w.members.filter(
                    (m) =>
                      m.stage === stage &&
                      (!filters.department ||
                        m.department === filters.department) &&
                      (!filters.orgId || m.orgId === filters.orgId) &&
                      (!filters.year ||
                        String(m.year || SCHOOL_YEAR) === filters.year),
                  ).length
                }
              </strong>
            </button>
          ))}
        </div>
        <Tabs
          items={["人员与阶段", "学校审核与材料待补"]}
          active={tab}
          onChange={setTab}
        />
        {tab === "学校审核与材料待补" ? (
          <RecordsTable records={records} open={setDetail} />
        ) : (
          <>
            <div className="school-list-toolbar">
              <SearchInput
                value={filters.query}
                onChange={(e) => {
                  setFilters((f) => ({ ...f, query: e.target.value }));
                  setPage(1);
                }}
                placeholder="搜索姓名或工号 / 学号"
              />
              <span>共 {people.length} 人</span>
            </div>
            <div className="table-scroll school-table">
              <table>
                <thead>
                  <tr>
                    <th>姓名 / 工号学号</th>
                    <th>所属支部</th>
                    <th>发展阶段</th>
                    <th>学校办理事项</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {people
                    .slice((currentPage - 1) * 10, currentPage * 10)
                    .map((m) => {
                      const tasks = w.records.filter(
                        (r) => r.profileId === m.id && !isSchoolComplete(r),
                      );
                      return (
                        <tr key={m.id}>
                          <td>
                            <strong>{m.name}</strong>
                            <small className="cell-subtext">{m.number}</small>
                          </td>
                          <td>{m.organization}</td>
                          <td>
                            <Badge>{m.stage}</Badge>
                          </td>
                          <td>
                            {tasks.length ? (
                              <button
                                className="text-button link"
                                onClick={() => setDetail(tasks[0])}
                              >
                                {tasks[0].status}
                              </button>
                            ) : (
                              "暂无待办"
                            )}
                          </td>
                          <td>
                            <button
                              className="text-button link"
                              onClick={() =>
                                navigate("development", {
                                  profileId: m.id,
                                  stage: m.stage,
                                  department: filters.department,
                                  orgId: filters.orgId,
                                  year: filters.year,
                                })
                              }
                            >
                              查看材料与流转
                              <ArrowUpRight size={13} />
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            </div>
            {!people.length && <Empty title="暂无符合条件的人员" />}
            <div className="school-pagination">
              <span>
                第 {currentPage} / {pageCount} 页
              </span>
              <button
                className="button secondary"
                disabled={currentPage === 1}
                onClick={() => setPage(currentPage - 1)}
              >
                上一页
              </button>
              <button
                className="button secondary"
                disabled={currentPage === pageCount}
                onClick={() => setPage(currentPage + 1)}
              >
                下一页
              </button>
            </div>
          </>
        )}
      </section>
      {detail && (
        <RecordModal record={detail} onClose={() => setDetail(null)} />
      )}
    </div>
  );
}

function SchoolLearningPlans() {
  const { session } = useApp();
  const { data, update, notify } = useStore();
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);
  function save(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const title = f.get("title").trim(),
      requirement = f.get("requirement").trim(),
      deadline = f.get("deadline");
    if (!title || !requirement || deadline < schoolToday()) {
      setError(
        new Error("请填写计划名称、任务要求，并选择不早于今天的截止日期。"),
      );
      return;
    }
    if (IS_LIVE || !hasPermission(session, "study.manage")) {
      setError(new Error("当前不能保存学习计划。"));
      return;
    }
    const plan = {
      id: crypto.randomUUID(),
      title,
      requirement,
      deadline,
      year: deadline.slice(0, 4),
      scope: f.get("scope"),
      status: "执行中",
    };
    const targetOrgs = wOrgs(f.get("scope"));
    update("schoolLearningPlans", (prev) => [plan, ...(prev || [])]);
    update("schoolWorkItems", (prev) => [
      ...prev,
      ...targetOrgs.map((org) => ({
        id: crypto.randomUUID(),
        planId: plan.id,
        business: "学习教育",
        title,
        orgId: org.id,
        organization: org.name,
        department: org.department,
        status: "待提交",
        dueDate: deadline,
        year: plan.year,
        stage: "",
        revision: 1,
        submittedName: org.secretary,
        submittedBy: "",
        archived: false,
        materials: [
          {
            name: "学习记录与院系核验意见",
            complete: false,
            version: "—",
            content: requirement,
          },
        ],
        history: [
          {
            id: crypto.randomUUID(),
            action: "学校建立学习任务",
            actor: session.user.name,
            at: new Date().toISOString(),
            version: 1,
            opinion: requirement,
          },
        ],
      })),
    ]);
    update("auditEntries", (prev) => [
      newAudit(session.user, "建立全校学习计划", "study_plan", plan.id),
      ...prev,
    ]);
    setAdding(false);
    notify(`学习计划已保存，已建立 ${targetOrgs.length} 项支部任务`);
  }
  const { orgs } = useManagedWorkspace();
  function wOrgs(scope) {
    return scope === "全校" ? orgs : orgs.filter((o) => o.department === scope);
  }
  return (
    <div className="school-plan-content">
      <div className="school-section-toolbar">
        <p>学校制定计划，院系核验督办，支部完成登记与材料提交。</p>
        <button
          className="button primary"
          disabled={IS_LIVE}
          onClick={() => {
            setError(null);
            setAdding(true);
          }}
        >
          <Plus size={16} />
          新建学习计划
        </button>
      </div>
      {(!IS_LIVE ? data.schoolLearningPlans || [] : []).map((p) => {
        const tasks = (data.schoolWorkItems || []).filter(
          (r) =>
            r.planId === p.id ||
            (!r.planId && p.id === "plan-1" && r.business === "学习教育"),
        );
        return (
          <div className="school-plan" key={p.id}>
            <BookOpen size={26} />
            <div>
              <h3>{p.title}</h3>
              <p>{p.requirement}</p>
              <small>
                {p.year}年度 · {p.scope} · {p.deadline} 截止
              </small>
              {!!tasks.length && (
                <p>
                  已完成 {tasks.filter(isSchoolComplete).length} /{" "}
                  {tasks.length} 个支部任务
                </p>
              )}
            </div>
            <Badge tone="blue">{p.status}</Badge>
          </div>
        );
      })}
      {IS_LIVE && (
        <Empty
          title="请在学习教育业务中查阅正式计划"
          description="计划编制服务暂不可用，请联系管理员或按学校现行流程办理。"
        />
      )}
      {adding && (
        <Modal title="新建学习计划" onClose={() => setAdding(false)}>
          <form onSubmit={save}>
            <Field label="计划名称" required>
              <input name="title" required maxLength={100} />
            </Field>
            <Field label="任务范围">
              <select name="scope">
                <option>全校</option>
                {[...new Set(orgs.map((o) => o.department))].map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </select>
            </Field>
            <Field label="截止日期" required>
              <input name="deadline" type="date" required min={schoolToday()} />
            </Field>
            <Field label="任务与材料要求" required>
              <textarea name="requirement" rows={4} required maxLength={2000} />
            </Field>
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <button
                className="button secondary"
                type="button"
                onClick={() => setAdding(false)}
              >
                取消
              </button>
              <button className="button primary">保存计划与支部任务</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

function SchoolIndicators({ year = SCHOOL_YEAR }) {
  const { session } = useApp();
  const { data, update, notify } = useStore();
  const [editing, setEditing] = useState(null);
  const [error, setError] = useState(null);
  function save(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget),
      name = f.get("name").trim(),
      requirement = f.get("requirement").trim(),
      weight = Number(f.get("weight"));
    if (!name || !requirement || weight < 0 || weight > 100) {
      setError(new Error("请填写完整指标名称、要求和 0–100 的权重。"));
      return;
    }
    if (IS_LIVE || !hasPermission(session, "assessment.configure")) {
      setError(new Error("当前不能修改学校年度指标。"));
      return;
    }
    update("schoolIndicators", (prev) =>
      prev.map((i) =>
        i.id === editing.id ? { ...i, name, requirement, weight } : i,
      ),
    );
    update("auditEntries", (prev) => [
      newAudit(
        session.user,
        "维护年度考核指标",
        "assessment_indicator",
        editing.id,
      ),
      ...prev,
    ]);
    setEditing(null);
    notify("2026年度考核指标已保存");
  }
  const items =
    !IS_LIVE && year === SCHOOL_YEAR ? data.schoolIndicators || [] : [];
  return (
    <div className="school-indicators">
      <p className="school-inline-guidance">
        2026年度 · 指标总权重 {items.reduce((sum, i) => sum + i.weight, 0)}% ·
        结果由学校授权人员人工确认
      </p>
      <div className="table-scroll school-table">
        <table>
          <thead>
            <tr>
              <th>编号</th>
              <th>指标名称</th>
              <th>材料与核验要求</th>
              <th>权重</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.id}>
                <td>{i.id}</td>
                <td>{i.name}</td>
                <td>{i.requirement}</td>
                <td>{i.weight}%</td>
                <td>
                  <button
                    className="text-button link"
                    onClick={() => {
                      setError(null);
                      setEditing(i);
                    }}
                  >
                    编辑指标
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!items.length && (
        <Empty
          title="暂无该年度指标"
          description="所选年度暂无指标，请选择已维护指标的年度。"
        />
      )}
      {editing && (
        <Modal title="编辑年度考核指标" onClose={() => setEditing(null)}>
          <form onSubmit={save}>
            <Field label="指标名称" required>
              <input
                name="name"
                defaultValue={editing.name}
                maxLength={100}
                required
              />
            </Field>
            <Field label="工作与佐证要求" required>
              <textarea
                name="requirement"
                rows={3}
                defaultValue={editing.requirement}
                required
                maxLength={2000}
              />
            </Field>
            <Field label="权重（%）" required>
              <input
                name="weight"
                type="number"
                min="0"
                max="100"
                defaultValue={editing.weight}
                required
              />
            </Field>
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <button
                className="button secondary"
                type="button"
                onClick={() => setEditing(null)}
              >
                取消
              </button>
              <button className="button primary">保存指标</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

export function SchoolStatistics() {
  const { navigate } = useApp();
  const w = useSchoolWorkspace();
  const [filters, setFilters] = useSchoolFilters();
  const [detail, setDetail] = useState(null);
  const [tab, setTab] = useState("组织进度");
  const records = filterSchoolRecords(w.records, filters);
  function exportReport() {
    exportCsv(
      [
        [
          "年度",
          "院系",
          "支部",
          "业务阶段",
          "业务",
          "事项",
          "状态",
          "提交人",
          "审核人",
          "版本",
          "归档状态",
        ],
        ...records.map((r) => [
          r.year,
          r.department,
          r.organization,
          r.stage,
          r.business,
          r.title,
          r.status,
          r.submittedName,
          r.reviewedBy || "",
          r.revision,
          r.archived ? "已归档" : "未归档",
        ]),
      ],
      `全校业务报表-${filters.year || "全部年度"}.csv`,
    );
  }
  return (
    <div className="school-workspace">
      <PageHeader
        title="全校统计与报表"
        subtitle="按院系、支部、年度和业务阶段筛选，从汇总继续追溯具体事项"
        action={
          <button className="button secondary" onClick={exportReport}>
            <DownloadSimple size={16} />
            导出筛选报表
          </button>
        }
      />
      <WorkspaceState w={w} />
      <section className="panel school-business-panel">
        <SchoolFilters
          filters={filters}
          setFilters={setFilters}
          orgs={w.orgs}
          business
          stage
        />
        <div className="school-stat-summary">
          {[
            ["登记事项", records.length],
            ["待审核", records.filter((r) => r.status === "待审核").length],
            ["逾期未办", records.filter((r) => isSchoolOverdue(r)).length],
            ["已通过 / 归档", records.filter(isSchoolComplete).length],
          ].map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
        <Tabs items={["组织进度", "事项明细"]} active={tab} onChange={setTab} />
        {tab === "组织进度" ? (
          <ProgressTable
            full
            records={records}
            orgs={w.orgs}
            department={filters.department}
            orgId={filters.orgId}
            onDetail={(row) => {
              setFilters((f) => ({
                ...f,
                department: row.department,
                orgId: row.orgId || "",
              }));
              setTab("事项明细");
            }}
          />
        ) : (
          <RecordsTable records={records} open={setDetail} />
        )}
        <p className="school-muted-note">
          统计口径：当前筛选范围内已登记的业务事项；完成数包含学校审核通过和已归档事项，未登记不视为已完成。
        </p>
      </section>
      {detail && (
        <RecordModal record={detail} onClose={() => setDetail(null)} />
      )}
    </div>
  );
}

export function SchoolNotices() {
  const [query, setQuery] = useState("");
  const [detail, setDetail] = useState(null);
  const rows = IS_LIVE ? [] : notices.filter((n) => n.title.includes(query));
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title="学校通知公告"
        subtitle="查阅学校工作安排、组织部通知与业务材料要求"
      />
      <div className="table-toolbar">
        <SearchInput
          placeholder="搜索通知标题"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {rows.map((n) => (
        <button
          className="school-notice"
          key={n.id}
          onClick={() => setDetail(n)}
        >
          <span>{n.date}</span>
          <div>
            <h3>{n.title}</h3>
            <small>{n.type}</small>
          </div>
          <ArrowRight size={16} />
        </button>
      ))}
      {!rows.length && <Empty title="暂无匹配通知" />}
      {detail && (
        <Modal title="学校通知" onClose={() => setDetail(null)}>
          <h2>{detail.title}</h2>
          <p className="body-copy">{detail.body}</p>
        </Modal>
      )}
    </section>
  );
}

export function SchoolManagement({ mode }) {
  const { session } = useApp();
  const { data, update, notify } = useStore();
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState(null);
  const titles = {
    accounts: [
      "本校人员与账号归属",
      "核对本校账号的人员身份、组织归属与业务权限",
    ],
    permissions: [
      "业务权限申请",
      "提出本校业务权限需求，记录申请依据并跟进处理状态",
    ],
    rules: ["学校业务参数", "维护本校业务年度、办理时限与材料要求"],
  };
  const rows = !IS_LIVE
    ? data.accounts.filter(
        (a) =>
          a.tenant_id === session.user.tenant_id &&
          a.role !== "system_admin" &&
          `${a.name} ${a.username} ${a.org_name}`.includes(query),
      )
    : [];
  const rules = !IS_LIVE ? data.schoolRules : null;
  function saveRules(e) {
    e.preventDefault();
    setError(null);
    if (IS_LIVE || !hasPermission(session, "admin.config")) {
      setError(new Error("当前不能保存学校业务参数。"));
      return;
    }
    const f = new FormData(e.currentTarget);
    const next = {
      year: f.get("year"),
      reviewDays: Number(f.get("reviewDays")),
      reminderDays: Number(f.get("reminderDays")),
      developmentMaterials: f.get("developmentMaterials").trim(),
      archiveRequirements: f.get("archiveRequirements").trim(),
      revision: rules.revision + 1,
    };
    if (
      !next.developmentMaterials ||
      !next.archiveRequirements ||
      !Number.isInteger(next.reviewDays) ||
      next.reviewDays < 1 ||
      next.reviewDays > 60 ||
      !Number.isInteger(next.reminderDays) ||
      next.reminderDays < 0 ||
      next.reminderDays > next.reviewDays
    ) {
      setError(
        new Error(
          "请填写完整材料要求；审核时限为1–60天，提醒提前天数须在时限范围内。",
        ),
      );
      return;
    }
    update("schoolRules", next);
    update("auditEntries", (prev) => [
      newAudit(
        session.user,
        "更新学校业务参数",
        "school_rules",
        session.user.tenant_id,
      ),
      ...prev,
    ]);
    notify(`学校业务参数 v${next.revision} 已保存`);
  }
  function apply(e) {
    e.preventDefault();
    setError(null);
    if (IS_LIVE || session.user.role !== "school_admin") {
      setError(new Error("当前不能保存业务权限申请。"));
      return;
    }
    const f = new FormData(e.currentTarget),
      reason = f.get("reason").trim();
    const account = rows.find((a) => a.id === f.get("account"));
    if (!account || !reason) {
      setError(new Error("请选择本校账号并填写申请依据。"));
      return;
    }
    const request = {
      id: crypto.randomUUID(),
      account: account.name,
      username: account.username,
      permission: f.get("permission"),
      reason,
      status: "待平台受理",
      actor: session.user.name,
      at: new Date().toISOString(),
      tenant_id: session.user.tenant_id,
    };
    update("schoolPermissionRequests", (prev) => [request, ...(prev || [])]);
    update("auditEntries", (prev) => [
      newAudit(
        session.user,
        "登记业务权限申请",
        "permission_request",
        request.id,
      ),
      ...prev,
    ]);
    setAdding(false);
    notify("权限申请已记录，当前账号权限保持原状态");
  }
  return (
    <section className="panel workspace-panel school-management">
      <PageHeader
        title={titles[mode][0]}
        subtitle={titles[mode][1]}
        action={
          mode === "permissions" && (
            <button
              className="button primary"
              disabled={IS_LIVE}
              onClick={() => {
                setError(null);
                setAdding(true);
              }}
            >
              <Plus size={16} />
              新建权限申请
            </button>
          )
        }
      />
      {mode === "accounts" ? (
        <>
          <div className="table-toolbar">
            <SearchInput
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索本校人员或账号"
            />
            <span className="toolbar-spacer" />
            <span className="small-text">本校共 {rows.length} 个账号</span>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>人员 / 账号</th>
                  <th>业务角色</th>
                  <th>组织归属</th>
                  <th>档案关联</th>
                  <th>账号状态</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <strong>{a.name}</strong>
                      <small className="cell-subtext">{a.username}</small>
                    </td>
                    <td>{roleLabel(a)}</td>
                    <td>{a.org_name}</td>
                    <td>
                      {a.profile_id
                        ? data.members.find((m) => m.id === a.profile_id)
                            ?.name || "待核实"
                        : ["member", "applicant"].includes(a.role)
                          ? "待关联"
                          : "管理岗位"}
                    </td>
                    <td>
                      <Badge tone={a.is_active ? "green" : "red"}>
                        {a.is_active ? "有效" : "停用"}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!rows.length && (
            <Empty
              title="暂无已加载的本校账号"
              description="正式账号归属以平台授权查询为准。"
            />
          )}
        </>
      ) : mode === "permissions" ? (
        <>
          <div className="school-inline-guidance">
            申请仅登记业务权限需求，由平台管理员按授权流程处理；本页不直接授予权限。
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>申请账号</th>
                  <th>业务权限</th>
                  <th>申请依据</th>
                  <th>提交时间</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {(!IS_LIVE ? data.schoolPermissionRequests || [] : [])
                  .filter((r) => r.tenant_id === session.user.tenant_id)
                  .map((r) => (
                    <tr key={r.id}>
                      <td>
                        {r.account}
                        <small className="cell-subtext">{r.username}</small>
                      </td>
                      <td>{r.permission}</td>
                      <td>{r.reason}</td>
                      <td>{r.at.slice(0, 10)}</td>
                      <td>
                        <Badge tone="orange">{r.status}</Badge>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          {!data.schoolPermissionRequests?.length && (
            <Empty
              title="暂无业务权限申请"
              description="可为本校账号登记所需业务范围及依据。"
            />
          )}
        </>
      ) : rules ? (
        <form className="school-rules-form" onSubmit={saveRules}>
          <div className="school-rule-version">
            <Badge tone="blue">当前 v{rules.revision}</Badge>
            <span>适用于本校业务，变更保留操作记录</span>
          </div>
          <div className="school-form-grid">
            <Field label="当前业务年度">
              <select name="year" defaultValue={rules.year}>
                <option>2026</option>
                <option>2025</option>
              </select>
            </Field>
            <Field label="建议审核时限（天）" required>
              <input
                type="number"
                name="reviewDays"
                min="1"
                max="60"
                defaultValue={rules.reviewDays}
                required
              />
            </Field>
            <Field label="截止前提醒（天）" required>
              <input
                type="number"
                name="reminderDays"
                min="0"
                max="60"
                defaultValue={rules.reminderDays}
                required
              />
            </Field>
          </div>
          <Field label="党员发展材料要求" required>
            <textarea
              name="developmentMaterials"
              rows={3}
              defaultValue={rules.developmentMaterials}
              required
              maxLength={2000}
            />
          </Field>
          <Field label="学校归档确认要求" required>
            <textarea
              name="archiveRequirements"
              rows={3}
              defaultValue={rules.archiveRequirements}
              required
              maxLength={2000}
            />
          </Field>
          {error && <ErrorBox error={error} />}
          <button className="button primary">保存学校业务参数</button>
        </form>
      ) : (
        <Empty
          title="尚未加载学校业务参数"
          description="正式业务参数需由学校授权服务读取和保存。"
        />
      )}
      <p className="school-muted-note">
        {mode === "rules"
          ? "年度考核指标在“考核与统计”维护，学习计划在“学习教育”编制。"
          : "账号开户与租户开通由平台管理员处理，学校负责核对归属及提出业务权限需求。"}
      </p>
      {adding && (
        <Modal title="新建业务权限申请" onClose={() => setAdding(false)}>
          <form onSubmit={apply}>
            <Field label="本校账号" required>
              <select name="account" required>
                <option value="">请选择账号</option>
                {rows.map((a) => (
                  <option value={a.id} key={a.id}>
                    {a.name} · {a.username}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="申请的业务权限">
              <select name="permission">
                <option>院系业务核验与督办</option>
                <option>组织生活审核</option>
                <option>年度考核人工确认</option>
                <option>本校业务统计与导出</option>
              </select>
            </Field>
            <Field label="权限范围与申请依据" required>
              <textarea
                name="reason"
                rows={4}
                required
                maxLength={2000}
                placeholder="说明院系、支部范围、岗位职责及申请依据"
              />
            </Field>
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <button
                type="button"
                className="button secondary"
                onClick={() => setAdding(false)}
              >
                取消
              </button>
              <button className="button primary">保存申请</button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}
