import { useEffect, useRef, useState, useMemo } from "react";
import {
  Plus,
  DownloadSimple,
  UsersThree,
  TreeStructure,
  Buildings,
  UserCircle,
  ArrowRight,
  FileText,
  CheckCircle,
  CaretRight,
  MagnifyingGlass,
  ArrowsLeftRight,
  UploadSimple,
} from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { backend, IS_LIVE } from "../api";
import {
  scopedMembers,
  scopedOrganizations,
  hasPermission,
  memberInScope,
  memberMatchesOrganization,
} from "../roles";
import { organizations, DEPARTMENTS, STAGES } from "../data";
import { normalizeMember, memberPayload } from "../contracts";
import {
  organizationForest,
  organizationType,
  organizationMatches,
  organizationMemberCount,
} from "../organization-tree";
import { todayIso } from "../league-eligibility";
import {
  PageHeader,
  PanelTitle,
  Tabs,
  SearchInput,
  Select,
  Badge,
  Pagination,
  Empty,
  Modal,
  Field,
  ErrorBox,
  Loading,
  exportCsv,
  downloadBlob,
} from "../components";
export function Organization() {
  const { data } = useStore();
  const { navigate, session, routeParams } = useApp();
  const [tab, setTab] = useState("党组织架构");
  const [query, setQuery] = useState(
    routeParams.organization || routeParams.department || "",
  );
  const [selected, setSelected] = useState(null);
  const [liveOrgs, setLiveOrgs] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(IS_LIVE);
  const [reload, setReload] = useState(0);
  const resolvedRouteQuery = useRef("");
  useEffect(() => {
    if (!IS_LIVE) return;
    let active = true;
    setLiveOrgs([]);
    setSelected(null);
    setError(null);
    setLoading(true);
    backend.organizations()
      .then((orgs) => { if (active) setLiveOrgs(orgs); })
      .catch((failure) => { if (active) setError(failure); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [session.user.id, session.user.tenant_id, reload]);
  const list = IS_LIVE ? liveOrgs : scopedOrganizations(session);
  useEffect(() => {
    const requested = String(routeParams.organization || "").trim();
    if (!requested || resolvedRouteQuery.current === requested) return;
    // Wait for the live organization response before deciding an id has no match.
    if (IS_LIVE && loading && !list.length) return;
    const match = list.find(
      (org) => String(org.id) === requested || org.name === requested,
    );
    resolvedRouteQuery.current = requested;
    if (match && query.trim() === requested) setQuery(match.name);
  }, [IS_LIVE, list, loading, query, routeParams.organization]);
  const term = query.trim();
  const filtered = list.filter((org) => organizationMatches(org, query));
  const forest = useMemo(() => organizationForest(list, query), [list, query]);
  const liveCount = (type) => loading || error ? "—" : list.filter((org) => org.org_type === type).length;
  const hasOrganizations = list.length > 0;
  const emptyState = (
    <Empty
      title={hasOrganizations ? "未找到匹配组织" : "暂无授权组织"}
      description={
        hasOrganizations
          ? `没有名称或编号与“${term}”匹配的党组织，请调整关键词或清除搜索。`
          : "当前账号未关联可查看的党组织，请联系学校党委组织部核对组织归属。"
      }
      action={
        hasOrganizations ? (
          <button className="button secondary" onClick={() => setQuery("")}>
            清除搜索
          </button>
        ) : (
          <button
            className="button secondary"
            onClick={() => navigate("dashboard")}
          >
            返回工作台
          </button>
        )
      }
    />
  );
  const selectedLeader = selected
    ? selected.leader_name || selected.secretary
    : "";
  const selectedMemberCount = selected
    ? organizationMemberCount(selected, data.members, !IS_LIVE)
    : null;
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title="组织建设"
        subtitle="夯实基层基础，建强战斗堡垒"
        action={
          <SearchInput
            placeholder="搜索党组织名称"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        }
      />
      <Tabs
        items={["党组织架构", "组织设置", "组织调整", "党委参考表"]}
        active={tab}
        onChange={setTab}
      />
      {error && <ErrorBox error={error} retry={() => setReload((value) => value + 1)} />}
      <div className="organization-layout">
        <div className="organization-main">
          {loading ? <Loading /> : error ? null : tab === "党组织架构" && IS_LIVE ? (
            forest.length ? (
              <div className="org-tree live-org-tree">
                <OrganizationNodes nodes={forest} select={setSelected} />
                <div className="org-tree-caption">
                  点击组织查看详情 · 仅展示当前账号授权范围内的组织与隶属关系
                </div>
              </div>
            ) : (
              emptyState
            )
          ) : tab === "党组织架构" &&
          !query &&
          !IS_LIVE &&
          ["school_admin", "system_admin"].includes(session.user.role) ? (
            <div className="org-tree">
              <button
                className="org-node root"
                onClick={() =>
                  setSelected({
                    name: "高校党委",
                    type: "学校党委",
                    secretary: "党委书记",
                    description: "统筹全校基层党组织建设。",
                  })
                }
              >
                <TreeStructure size={18} />
                高校党委
              </button>
              <div className="tree-stem" />
              <div className="org-groups">
                {["教工党委", "学生党委", "直属单位党委"].map((name, i) => (
                  <div className="org-group" key={name}>
                    <button
                      className="org-node parent"
                      onClick={() =>
                        setSelected({
                          name,
                          type: "二级党组织",
                          secretary: "组织负责人",
                          description: `下设${i === 0 ? "教工" : i === 1 ? "学生" : "直属单位"}党支部`,
                        })
                      }
                    >
                      <Buildings size={17} />
                      {name}
                    </button>
                    <div className="tree-stem" />
                    <div className="org-branches">
                      {(i === 0
                        ? ["机关党支部", "学院党支部"]
                        : i === 1
                          ? ["研究生党支部", "本科生党支部"]
                          : ["图书馆党支部", "后勤党支部"]
                      ).map((n, j) => (
                        <button
                          className="org-node leaf"
                          key={n}
                          onClick={() => setSelected(organizations[i * 6 + j])}
                        >
                          {n}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <div className="org-tree-caption">
                点击组织节点查看详情 <span>·</span> 共 12 个二级党组织、68
                个党支部
              </div>
            </div>
          ) : tab === "组织调整" || tab === "党委参考表" ? (
            <div className="organization-guidance">
              <TreeStructure size={42} weight="duotone" />
              <h3>
                {tab === "组织调整" ? "组织调整工作指引" : "党委工作参考"}
              </h3>
              <p>
                {tab === "组织调整"
                  ? "组织设立、撤销、换届与隶属关系调整须按学校组织工作程序办理。请联系党委组织部核对正式组织信息。"
                  : "可从党建工作库查阅组织建设相关制度，使用党建智能体辅助梳理材料清单。"}
              </p>
              <button
                className="button secondary"
                onClick={() => navigate("knowledge")}
              >
                查阅工作制度
                <ArrowRight size={15} />
              </button>
            </div>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>组织名称</th>
                    <th>类型</th>
                    <th>书记</th>
                    <th>在册人员</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.slice(0, 18).map((o) => {
                    const memberCount = organizationMemberCount(
                      o,
                      data.members,
                      !IS_LIVE,
                    );
                    return (
                      <tr key={o.id}>
                        <td>{o.name}</td>
                        <td>{organizationType(o)}</td>
                        <td>{o.leader_name || o.secretary || "未登记"}</td>
                        <td>{memberCount == null ? "—" : `${memberCount} 人`}</td>
                        <td>
                          <button
                            className="text-button link"
                            onClick={() => setSelected(o)}
                          >
                            查看
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {!filtered.length && emptyState}
            </div>
          )}
        </div>
        <aside className="org-summary">
          <PanelTitle title={IS_LIVE ? "授权组织概况" : "组织概况"} />
          {[
            {
              icon: UsersThree,
              label: "党委",
              value: IS_LIVE ? liveCount("school") : ["school_admin", "system_admin"].includes(
                session.user.role,
              )
                ? 1
                : "—",
            },
            {
              icon: Buildings,
              label: "二级党组织",
              value: IS_LIVE ? liveCount("department") :
                session.user.role === "department_admin"
                  ? 1
                  : ["school_admin", "system_admin"].includes(session.user.role)
                    ? 12
                    : "—",
            },
            {
              icon: TreeStructure,
              label: "党支部",
              value: IS_LIVE ? liveCount("branch") : list.length,
            },
          ].map((x) => (
            <div className="org-summary-item" key={x.label}>
              <div className="stat-icon red">
                <x.icon size={25} weight="duotone" />
              </div>
              <div>
                <p>{x.label}</p>
                <strong>
                  {x.value}
                  <small>个</small>
                </strong>
              </div>
            </div>
          ))}
          <div className="org-summary-tip">
            组织信息以学校党委组织部登记为准。
          </div>
        </aside>
      </div>
      {selected && (
        <Modal title="党组织详情" onClose={() => setSelected(null)}>
          <div className="detail-profile">
            <div className="stat-icon red">
              <TreeStructure size={30} weight="duotone" />
            </div>
            <div>
              <h3>{selected.name}</h3>
              <p>{IS_LIVE ? list.find((org) => org.id === selected.parent_id)?.name || "当前授权组织" : selected.department || "高校党委"}</p>
            </div>
          </div>
          <dl className="detail-list">
            <dt>组织类型</dt>
            <dd>{organizationType(selected)}</dd>
            <dt>支部书记</dt>
            <dd>{selectedLeader || "未登记"}</dd>
            <dt>在册人员</dt>
            <dd>
              {selectedMemberCount == null
                ? "按授权名册统计"
                : `${selectedMemberCount} 人`}
            </dd>
          </dl>
          {selected.id ? (
            <button
              className="button primary"
              onClick={() => {
                navigate("members", {
                  organization: selected.name,
                  orgId: selected.id,
                });
                setSelected(null);
              }}
            >
              查看组织党员
              <ArrowRight size={16} />
            </button>
          ) : (
            <p className="inline-note">
              请选择具体党支部查看党员名册。
            </p>
          )}
        </Modal>
      )}
    </section>
  );
}
function OrganizationNodes({ nodes, select, depth = 0 }) {
  return (
    <ul className="live-org-nodes" aria-label={depth === 0 ? "已授权党组织架构" : "下级党组织"}>
      {nodes.map((node) => (
        <li key={node.id}>
          <button
            className={`org-node ${depth === 0 ? "root" : node.children.length ? "parent" : "leaf"}`}
            data-org-id={node.id}
            onClick={() => select(node)}
          >
            <TreeStructure size={18} />
            <span>{node.name}<small>{organizationType(node)}</small></span>
          </button>
          {node.children.length > 0 && (
            <OrganizationNodes nodes={node.children} select={select} depth={depth + 1} />
          )}
        </li>
      ))}
    </ul>
  );
}
export function Members({ mode = "members" }) {
  const { data, update, notify } = useStore();
  const { routeParams, session, navigate } = useApp();
  const [tab, setTab] = useState(
    mode === "development"
      ? "党员发展"
      : mode === "archive"
        ? "党员档案"
        : "党员信息",
  );
  const [query, setQuery] = useState(routeParams.query || "");
  const [org, setOrg] = useState(
    routeParams.organization || routeParams.department || "",
  );
  const [orgId, setOrgId] = useState(
    routeParams.orgId || routeParams.org_id || routeParams.org_unit_id || "",
  );
  const [stage, setStage] = useState(routeParams.stage || "");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(8);
  const [detail, setDetail] = useState(null);
  const [importDialog, setImportDialog] = useState(false);
  const [importFile, setImportFile] = useState(null);
  const [importNote, setImportNote] = useState("");
  const [importReport, setImportReport] = useState(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [orgOptions, setOrgOptions] = useState(() =>
    IS_LIVE ? [] : scopedOrganizations(session),
  );
  const canCreate =
    hasPermission(session, "member.stage_transition") &&
    session.user.role !== "school_admin";
  const canImport = hasPermission(session, "member.stage_transition");
  async function load() {
    if (!IS_LIVE) return;
    setBusy(true);
    setError(null);
    try {
      const [res, orgs] = await Promise.all([
        backend.members(),
        backend.organizations(),
      ]);
      update("members", (res.items || []).map(normalizeMember));
      setOrgOptions(orgs);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    load();
  }, []);
  useEffect(() => {
    setPage(1);
  }, [query, org, orgId, stage, size, tab]);
  useEffect(() => {
    if (!orgId) return;
    const match = orgOptions.find((o) => String(o.id) === String(orgId));
    if (match?.name && match.name !== org) setOrg(match.name);
  }, [orgId, orgOptions, org]);
  function openImportDialog() {
    setImportDialog(true);
    setImportFile(null);
    setImportNote("");
    setImportReport(null);
    setImportError(null);
  }
  function closeImportDialog(force = false) {
    if (importBusy && !force) return;
    setImportDialog(false);
    setImportFile(null);
    setImportNote("");
    setImportReport(null);
    setImportError(null);
  }
  async function downloadRosterTemplate() {
    setImportError(null);
    try {
      downloadBlob(
        await backend.rosterTemplate(),
        "党员名册导入模板.xlsx",
      );
      notify("名册导入模板已下载");
    } catch (e) {
      setImportError(e);
    }
  }
  async function previewRosterImport(e) {
    e.preventDefault();
    setImportError(null);
    if (!importFile) {
      setImportError(new Error("请选择按模板填写的 .xlsx 名册文件。"));
      return;
    }
    if (importNote.trim().length < 4) {
      setImportError(new Error("请填写至少 4 个字的名册来源说明。"));
      return;
    }
    setImportBusy(true);
    try {
      setImportReport(
        await backend.importRoster({
          file: importFile,
          sourceNote: importNote.trim(),
          dryRun: true,
        }),
      );
    } catch (e) {
      setImportError(e);
    } finally {
      setImportBusy(false);
    }
  }
  async function commitRosterImport() {
    if (!importFile || !importReport || importReport.failed > 0) return;
    setImportBusy(true);
    setImportError(null);
    try {
      const result = await backend.importRoster({
        file: importFile,
        sourceNote: importNote.trim(),
        dryRun: false,
      });
      await load();
      notify(`本次已登记 ${result.created || 0} 份档案，已有记录 ${result.skipped || 0} 份未改动`);
      closeImportDialog(true);
    } catch (e) {
      setImportError(e);
    } finally {
      setImportBusy(false);
    }
  }
  const organizationOptions = useMemo(() => {
    const values = new Set(orgOptions.map((o) => o.department || o.name));
    if (org) values.add(org);
    return [...values];
  }, [orgOptions, org]);
  const orgScopeIds = useMemo(() => {
    if (!orgId) return null;
    const children = new Map();
    for (const o of orgOptions) {
      const parent = String(o.parent_id || "");
      if (!children.has(parent)) children.set(parent, []);
      children.get(parent).push(String(o.id));
    }
    const ids = new Set([String(orgId)]);
    const queue = [String(orgId)];
    while (queue.length) {
      const current = queue.pop();
      for (const child of children.get(current) || []) {
        if (ids.has(child)) continue;
        ids.add(child);
        queue.push(child);
      }
    }
    return ids;
  }, [orgId, orgOptions]);
  const filtered = useMemo(
    () =>
      scopedMembers(data, session, IS_LIVE).filter(
        (m) =>
          (!query ||
            `${m.name} ${m.number} ${m.department}`
              .toLowerCase()
              .includes(query.toLowerCase())) &&
          memberMatchesOrganization(m, org, orgScopeIds) &&
          (!stage || m.stage === stage) &&
          (tab !== "党员转正" || m.stage === "预备党员"),
      ),
    [data.members, query, org, orgScopeIds, stage, tab, session],
  );
  const pages = Math.max(1, Math.ceil(filtered.length / size));
  const actualPage = Math.min(page, pages);
  const rows = filtered.slice((actualPage - 1) * size, actualPage * size);
  async function addMember(e) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const organization = orgOptions.find((o) => o.id === form.get("orgId"));
      if (!organization)
        throw new Error(
          "当前账号没有可登记的组织，请先联系管理员核对组织归属。",
        );
      let member = {
        id: crypto.randomUUID(),
        name: form.get("name").trim(),
        number: String(form.get("number") || "").trim(),
        orgId: organization.id,
        organization: organization.name,
        department: organization.department || organization.name,
        stage: form.get("stage"),
        gender: form.get("gender") || "未提供",
        phone: "—",
        status: "正常",
        joined: new Date().toISOString().slice(0, 10),
        year: 2026,
        birth_date: String(form.get("birth_date") || ""),
        league_joined_on: String(form.get("league_joined_on") || ""),
        note: String(form.get("note") || "").trim(),
      };
      if (!member.name || (!IS_LIVE && !member.number))
        throw new Error("姓名和学号 / 工号不能为空。");
      if (
        member.birth_date &&
        member.league_joined_on &&
        member.league_joined_on < member.birth_date
      )
        throw new Error("入团时间不能早于出生年月。");
      if (!IS_LIVE && data.members.some((m) => m.number === member.number))
        throw new Error("该学号 / 工号已存在，请核对后重试。");
      if (IS_LIVE) {
        member = normalizeMember(
          await backend.createMember(memberPayload(member)),
        );
      }
      update("members", (prev) => [member, ...prev]);
      setAdding(false);
      setQuery(member.name);
      setOrg("");
      setStage("");
      notify("党员信息已登记");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  async function exportMembers() {
    try {
      if (IS_LIVE) {
        downloadBlob(await backend.exportRoster(), "党员名册.csv");
      } else {
        exportCsv(
          [
            ["姓名", "学号 / 工号", "所属组织", "党员类型", "状态"],
            ...filtered.map((m) => [
              m.name,
              m.number,
              m.organization,
              m.stage,
              m.status,
            ]),
          ],
          "党员名册.csv",
        );
      }
      notify("名册已导出");
    } catch (e) {
      notify(e.message, "error");
    }
  }
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title={
          mode === "development"
            ? "发展党员"
            : mode === "archive"
              ? "党员档案"
              : "党员管理"
        }
        subtitle="规范党员管理，记录成长足迹"
      />
      <Tabs
        items={["党员信息", "党员发展", "党员转正", "党员组织关系", "党员档案"]}
        active={tab}
        onChange={setTab}
      />
      <div className="table-toolbar">
        <SearchInput
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={
            IS_LIVE ? "搜索已加载的姓名 / 编号" : "请输入姓名 / 学号 / 工号"
          }
        />
        <Select
          label="所属组织"
          value={org}
          onChange={(e) => {
            setOrg(e.target.value);
            setOrgId("");
          }}
        >
          <option value="">所属组织</option>
          {organizationOptions.map((o) => (
            <option key={o}>{o}</option>
          ))}
        </Select>
        <Select
          label="党员状态"
          value={stage}
          onChange={(e) => setStage(e.target.value)}
        >
          <option value="">党员类型</option>
          {STAGES.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </Select>
        <div className="toolbar-spacer" />
        <button className="button secondary" onClick={exportMembers}>
          <DownloadSimple size={17} />
          导出名册
        </button>
        {canImport && (
          <button className="button secondary" onClick={openImportDialog}>
            <UploadSimple size={17} />
            {IS_LIVE ? "导入本校档案" : "查看档案导入说明"}
          </button>
        )}
        {canCreate && (
          <button
            className="button primary"
            onClick={() => {
              setAdding(true);
              setError(null);
            }}
          >
            <Plus size={18} />
            新增党员
          </button>
        )}
      </div>
      {IS_LIVE && (
        <div className="inline-note">
          已加载前100条授权记录；名册导出覆盖当前账号完整授权范围。
        </div>
      )}
      {error && !adding && <ErrorBox error={error} retry={load} />}
      <div className="table-scroll">
        <table className="member-table">
          <thead>
            <tr>
              <th>序号</th>
              <th>姓名</th>
              <th>{IS_LIVE ? "档案编号 / 脱敏证件号" : "学号 / 工号"}</th>
              <th>所属组织</th>
              <th>党员类型</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((m, i) => (
              <tr key={m.id}>
                <td>{(actualPage - 1) * size + i + 1}</td>
                <td>
                  <button className="member-name" onClick={() => setDetail(m)}>
                    <span className={`member-initial avatar-${i % 4}`}>
                      {m.name[0]}
                    </span>
                    {m.name}
                  </button>
                </td>
                <td className="numeric">{m.number}</td>
                <td className="org-cell">{m.organization}</td>
                <td>{m.stage}</td>
                <td>
                  <Badge>{m.status}</Badge>
                </td>
                <td>
                  <button
                    className="text-button link"
                    onClick={() => setDetail(m)}
                  >
                    {tab === "党员发展"
                      ? "查看进程"
                      : tab === "党员组织关系"
                        ? "查看关系"
                        : "查看"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {busy && !adding && <Loading />}
        {!rows.length && !busy && (
          <Empty
            title={
              orgId ? "未找到符合条件的人员" : "暂无符合条件的记录"
            }
            description={
              orgId
                ? `已按“${org || "所选组织"}”筛选；该组织及其下级组织在当前条件下没有可显示的名册记录。`
                : "试试调整搜索关键词或筛选条件。"
            }
            action={
              orgId ? (
                <button
                  className="button secondary"
                  onClick={() => {
                    setOrg("");
                    setOrgId("");
                  }}
                >
                  清除组织筛选
                </button>
              ) : undefined
            }
          />
        )}
        {tab === "党员转正" &&
          rows.length > 0 &&
          !rows.some((m) => m.stage === "预备党员") && (
            <Empty
              title="本页暂无预备党员"
              description="请使用“党员类型”筛选预备党员。"
            />
          )}
      </div>
      <div className="table-footer">
        <span className="table-hint">
          {!IS_LIVE ? "党员名册 · 本地保存" : "授权名册 · 人工登记"}
        </span>
        <Pagination
          page={actualPage}
          pages={pages}
          total={filtered.length}
          onChange={setPage}
        />
        <Select
          label="每页条数"
          value={size}
          onChange={(e) => setSize(Number(e.target.value))}
        >
          <option value={8}>8条 / 页</option>
          <option value={15}>15条 / 页</option>
          <option value={30}>30条 / 页</option>
        </Select>
      </div>
      {tab === "党员发展" && (
        <div className="development-guide">
          <PanelTitle title="党员发展工作流程" />
          <div className="stage-stepper">
            {STAGES.map((s, i) => (
              <div key={s}>
                <span>{i + 1}</span>
                <p>{s}</p>
                {i < 4 && <ArrowRight size={18} />}
              </div>
            ))}
          </div>
          <p>
            材料校验和智能建议用于辅助工作，阶段变更须由有权限的组织人员人工审核。
          </p>
        </div>
      )}
      {tab === "党员组织关系" && (
        <div className="inline-note">
          <ArrowsLeftRight size={17} />
          组织关系转入 /
          转出须登记介绍信与回执。{IS_LIVE ? <button className="text-button link" onClick={() => navigate(session.user.role === "school_admin" ? "school-development" : "development", { businessTab: "组织接转" })}>进入组织接转台账</button> : "组织关系以接转台账及回执为准。"}
        </div>
      )}
      {adding && (
        <Modal title="新增党员信息" onClose={() => setAdding(false)} wide>
          <form onSubmit={addMember}>
            <div className="form-grid">
              <Field label="姓名" required>
                <input
                  name="name"
                  maxLength={30}
                  required
                  placeholder="请输入姓名"
                />
              </Field>
              {!IS_LIVE && (
                <Field label="学号 / 工号" required>
                  <input
                    name="number"
                    maxLength={40}
                    required
                    placeholder="请输入唯一编号"
                  />
                </Field>
              )}
              <Field label="所属组织" required>
                <select name="orgId" required>
                  {orgOptions.map((o) => (
                    <option value={o.id} key={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="党员类型" required>
                <select name="stage" defaultValue="入党申请人">
                  {STAGES.map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </Field>
              <Field label="出生年月">
                <input
                  name="birth_date"
                  type="date"
                  max={todayIso()}
                  aria-label="出生年月"
                />
              </Field>
              <Field label="入团时间">
                <input
                  name="league_joined_on"
                  type="date"
                  max={todayIso()}
                  aria-label="入团时间"
                />
              </Field>
              {!IS_LIVE && (
                <Field label="性别">
                  <select name="gender">
                    <option>男</option>
                    <option>女</option>
                    <option>未登记</option>
                  </select>
                </Field>
              )}
              {!IS_LIVE && (
                <Field label="登记说明" full>
                  <textarea
                    name="note"
                    rows={3}
                    placeholder="请输入登记依据或备注"
                    maxLength={500}
                  />
                </Field>
              )}
              {IS_LIVE && (
                <div className="inline-note field full">
                  请核对姓名、所属组织和当前发展阶段后登记，其他信息按学校档案管理要求维护。
                  出生年月与入团时间用于核验团组织推优资格；可后补，但缺项无法登记推优。
                </div>
              )}
            </div>
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <button
                type="button"
                className="button secondary"
                onClick={() => setAdding(false)}
              >
                取消
              </button>
              <button className="button primary" disabled={busy}>
                {busy ? "保存中…" : "确认登记"}
              </button>
            </div>
          </form>
        </Modal>
      )}
      {importDialog && (
        <Modal
          title="导入本校档案"
          wide
          flat
          className="roster-import-modal"
          onClose={closeImportDialog}
        >
          {!IS_LIVE ? (
            <div className="archive-import-unavailable">
              <UploadSimple size={34} weight="duotone" />
              <h3>当前未连接学校档案导入服务</h3>
              <p>
                本地演示模式不会读取或写入真实学校档案。接入真实服务后，学校管理员或被授权的组织人员可按以下流程导入本校名册。
              </p>
              <ol>
                <li>在“党员档案与材料”中下载名册导入模板。</li>
                <li>按当前学校的组织权限填写名册和来源说明。</li>
                <li>上传后先预检，确认逐行结果无误再正式登记。</li>
              </ol>
              <p className="page-note">
                本流程只登记基础档案台账，不导入历史材料原件、不建立账号关联，不改变已有人员阶段，也不代替材料接收、审核或组织关系办理。
              </p>
              <div className="modal-actions">
                <button
                  type="button"
                  className="button secondary"
                  onClick={closeImportDialog}
                >
                  关闭
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="archive-import-intro">
                <strong>按学校权限导入人员名册</strong>
                <p>
                  先下载模板并填写名册来源；系统会按当前账号可管理的组织逐行预检，确认后才登记基础档案台账。已有同名同组织记录将跳过，不会被覆盖；历史材料原件和账号关联需另按业务流程办理。
                </p>
              </div>
              <div className="archive-import-template">
                <div>
                  <span className="archive-import-step">1</span>
                  <div>
                    <strong>下载并填写名册模板</strong>
                    <p>模板包含可用组织与阶段填写说明，仅支持 .xlsx 文件。</p>
                  </div>
                </div>
                <button
                  type="button"
                  className="button secondary"
                  onClick={downloadRosterTemplate}
                  disabled={importBusy}
                >
                  <DownloadSimple size={17} />
                  下载导入模板
                </button>
              </div>
              <form onSubmit={previewRosterImport}>
                <div className="archive-import-form">
                  <Field label="名册文件" required full>
                    <input
                      type="file"
                      accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                      onChange={(e) => {
                        setImportFile(e.target.files?.[0] || null);
                        setImportReport(null);
                        setImportError(null);
                      }}
                      disabled={importBusy}
                    />
                    <small className="field-help">
                      {importFile
                        ? `${importFile.name} · ${(importFile.size / 1024 / 1024).toFixed(2)} MB`
                        : "请选择按模板填写的 Excel 文件。"}
                    </small>
                  </Field>
                  <Field label="名册来源说明" required full>
                    <input
                      value={importNote}
                      onChange={(e) => {
                        setImportNote(e.target.value);
                        setImportReport(null);
                        setImportError(null);
                      }}
                      maxLength={200}
                      placeholder="例如：校内党员管理台账导出 2026-10-25"
                      disabled={importBusy}
                    />
                    <small className="field-help">
                      4–200 个字，将随本次导入写入审计记录，用于事后核对名册来路。
                    </small>
                  </Field>
                </div>
                {importError && <ErrorBox error={importError} />}
                <div className="modal-actions">
                  <button
                    type="button"
                    className="button secondary"
                    onClick={closeImportDialog}
                    disabled={importBusy}
                  >
                    取消
                  </button>
                  <button
                    className="button primary"
                    disabled={importBusy || !importFile}
                  >
                    {importBusy ? "正在预检…" : "预检文件"}
                  </button>
                </div>
              </form>
              {importReport && (
                <section className="archive-import-report" aria-live="polite">
                  <div className="archive-import-report-heading">
                    <div>
                      <h3>预检结果</h3>
                      <p>预检不会写入档案，确认后再执行正式登记。</p>
                    </div>
                    <div className="archive-import-counts">
                      <span>共 {importReport.total_rows || 0} 行</span>
                      <span className="is-created">可登记 {importReport.created || 0}</span>
                      <span className="is-skipped">跳过 {importReport.skipped || 0}</span>
                      <span className={importReport.failed ? "is-failed" : ""}>
                        错误 {importReport.failed || 0}
                      </span>
                    </div>
                  </div>
                  {!!importReport.rows?.length && (
                    <div className="archive-import-report-table">
                      <table>
                        <thead>
                          <tr>
                            <th>行号</th>
                            <th>姓名</th>
                            <th>结果</th>
                            <th>说明</th>
                          </tr>
                        </thead>
                        <tbody>
                          {importReport.rows.slice(0, 100).map((row) => (
                            <tr key={`${row.row}-${row.name}`}>
                              <td>{row.row}</td>
                              <td>{row.name || "—"}</td>
                              <td>
                                <Badge
                                  tone={
                                    row.status === "error"
                                      ? "orange"
                                      : row.status === "skipped"
                                        ? "gray"
                                        : "green"
                                  }
                                >
                                  {row.status === "error"
                                    ? "错误"
                                    : row.status === "skipped"
                                      ? "跳过"
                                      : "可登记"}
                                </Badge>
                              </td>
                              <td>{row.message || "校验通过"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {importReport.rows.length > 100 && (
                        <p className="page-note">仅展示前 100 行结果，完整结果以本次预检返回为准。</p>
                      )}
                    </div>
                  )}
                  <div className="modal-actions">
                    {importReport.failed > 0 && (
                      <span className="archive-import-blocked">
                        请修正文件中的错误后重新预检
                      </span>
                    )}
                    <button
                      type="button"
                      className="button primary"
                      onClick={commitRosterImport}
                      disabled={
                        importBusy ||
                        importReport.failed > 0 ||
                        importReport.created === 0
                      }
                    >
                      {importBusy
                        ? "正在登记…"
                        : `确认登记 ${importReport.created || 0} 份档案`}
                    </button>
                  </div>
                </section>
              )}
            </>
          )}
        </Modal>
      )}
      {detail && (
        <Modal
          title="党员档案"
          wide
          flat
          className="member-archive-modal"
          onClose={() => setDetail(null)}
        >
          <div className="detail-profile member-archive-profile">
            <div className="large-member-avatar">{detail.name[0]}</div>
            <div className="member-archive-identity">
              <h3>{detail.name}</h3>
              <p>{detail.number}</p>
            </div>
            <Badge>{detail.stage}</Badge>
          </div>
          <dl className="member-archive-fields">
            {[
              ["所属组织", detail.organization],
              ["性别", detail.gender],
              ["联系电话", detail.phone],
              ["登记日期", detail.joined],
              ["组织关系", detail.relation || "在册"],
              ["当前状态", <Badge>{detail.status}</Badge>],
            ].map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <section className="member-archive-development" aria-label="发展阶段">
            <h3>发展阶段</h3>
            <ol className="member-archive-stages">
              {STAGES.map((s, i) => (
                <li
                  className={`${i <= STAGES.indexOf(detail.stage) ? "is-complete" : ""} ${s === detail.stage ? "is-current" : ""}`}
                  aria-current={s === detail.stage ? "step" : undefined}
                  key={s}
                >
                  <CheckCircle
                    size={20}
                    aria-hidden="true"
                    weight={
                      i <= STAGES.indexOf(detail.stage) ? "fill" : "regular"
                    }
                  />
                  <span>{s}</span>
                  {s === detail.stage && <Badge tone="red">当前阶段</Badge>}
                </li>
              ))}
            </ol>
          </section>
          <p className="member-archive-note">
            档案阶段仅展示已登记信息，具体材料与审核记录以正式业务库为准。
          </p>
        </Modal>
      )}
    </section>
  );
}
