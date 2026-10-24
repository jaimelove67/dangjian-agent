import { useEffect, useState, useMemo } from "react";
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
} from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { backend, IS_LIVE } from "../api";
import {
  scopedMembers,
  scopedOrganizations,
  hasPermission,
  memberInScope,
} from "../roles";
import { organizations, DEPARTMENTS, STAGES } from "../data";
import { normalizeMember, memberPayload } from "../contracts";
import { organizationForest, organizationType } from "../organization-tree";
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
  const filtered = list.filter((o) => o.name.includes(query.trim()));
  const forest = useMemo(() => organizationForest(list, query), [list, query]);
  const liveCount = (type) => loading || error ? "—" : list.filter((org) => org.org_type === type).length;
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
              <Empty title={query ? "未找到匹配组织" : "暂无授权组织"} />
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
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.slice(0, 18).map((o) => (
                    <tr key={o.id}>
                      <td>{o.name}</td>
                      <td>{organizationType(o)}</td>
                      <td>{o.secretary || "—"}</td>
                      <td>
                        <button
                          className="text-button link"
                          onClick={() => setSelected(o)}
                        >
                          查看
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!filtered.length && <Empty />}
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
            <dd>{selected.secretary || "待登记"}</dd>
            <dt>在册党员</dt>
            <dd>
              {!IS_LIVE && selected.id
                ? `${data.members.filter((m) => m.orgId === selected.id).length} 人`
                : "以授权名册为准"}
            </dd>
          </dl>
          <button
            className="button primary"
            onClick={() => {
              navigate("members", { organization: selected.name });
              setSelected(null);
            }}
          >
            查看组织党员
            <ArrowRight size={16} />
          </button>
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
  const [stage, setStage] = useState(routeParams.stage || "");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(8);
  const [detail, setDetail] = useState(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [orgOptions, setOrgOptions] = useState(() =>
    IS_LIVE ? [] : scopedOrganizations(session),
  );
  const canCreate =
    hasPermission(session, "member.stage_transition") &&
    session.user.role !== "school_admin";
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
  }, [query, org, stage, size, tab]);
  const filtered = useMemo(
    () =>
      scopedMembers(data, session, IS_LIVE).filter(
        (m) =>
          (!query ||
            `${m.name} ${m.number} ${m.department}`
              .toLowerCase()
              .includes(query.toLowerCase())) &&
          (!org || m.organization === org || m.department === org) &&
          (!stage || m.stage === stage) &&
          (tab !== "党员转正" || m.stage === "预备党员"),
      ),
    [data.members, query, org, stage, tab, session],
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
        note: String(form.get("note") || "").trim(),
      };
      if (!member.name || (!IS_LIVE && !member.number))
        throw new Error("姓名和学号 / 工号不能为空。");
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
          onChange={(e) => setOrg(e.target.value)}
        >
          <option value="">所属组织</option>
          {[...new Set(orgOptions.map((o) => o.department || o.name))].map(
            (o) => (
              <option key={o}>{o}</option>
            ),
          )}
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
        {!rows.length && !busy && <Empty />}
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
