import { useRef, useState } from "react";
import {
  IdentificationCard,
  UploadSimple,
  FileText,
  DownloadSimple,
  Clock,
  CheckCircle,
  ShieldCheck,
  ArrowRight,
  Sparkle,
  Books,
} from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE, getSession } from "../api";
import { roleApi } from "../role-api";
import { useOwnWorkspace } from "../role-hooks";
import { isSelfService, roleLabel } from "../roles";
import { MATERIAL_CATEGORIES, newAudit } from "../role-data";
import { saveDemoFile, getDemoFile } from "../demo-files";
import { validateMaterialFile } from "../material-validation";
import { STAGES } from "../data";
import { OwnReviews } from "../components/OwnReviews";
import { MaterialSuggestions, useMaterialDraft } from "../components/MaterialSuggestions";
import {
  PageHeader,
  PanelTitle,
  Badge,
  Modal,
  Field,
  Tabs,
  SearchInput,
  Empty,
  ErrorBox,
  Loading,
  Pagination,
  downloadBlob,
} from "../components";
export function PersonalHome() {
  const { session, navigate } = useApp();
  const own = useOwnWorkspace();
  const applicant = session.user.role === "applicant";
  return (
    <div className="personal-workspace">
      <section className="role-welcome personal-welcome">
        <div>
          <span className="eyebrow">
            我的党建空间 <span>·</span> {roleLabel(session.user)}
          </span>
          <h1>{session.user.name}，您好</h1>
          <p>
            {applicant
              ? "每一步成长，都从认真准备开始。"
              : "让每一次学习与实践，都留下成长的足迹。"}
          </p>
          <div className="welcome-actions">
            <button
              className="button primary"
              onClick={() => navigate("self-materials")}
            >
              <UploadSimple size={16} />
              提交个人材料
            </button>
            <button
              className="button secondary"
              onClick={() => navigate("assistant")}
            >
              <Sparkle size={16} />
              向智能体提问
            </button>
          </div>
        </div>
        <img src="/assets/assistant-avatar.png" alt="党建智能助手" />
      </section>
      {own.error && <ErrorBox error={own.error} retry={own.reload} />}
      <div className="role-metrics">
        <div>
          <span className="metric-icon red">
            <IdentificationCard size={24} />
          </span>
          <div>
            <p>当前登记阶段</p>
            <strong className="text-metric">
              {own.loading ? "加载中" : own.profile?.stage || "尚未关联档案"}
            </strong>
          </div>
        </div>
        <div>
          <span className="metric-icon blue">
            <FileText size={24} />
          </span>
          <div>
            <p>已提交材料</p>
            <strong>
              {own.total}
              <small>份</small>
            </strong>
          </div>
        </div>
        <div>
          <span className="metric-icon green">
            <ShieldCheck size={24} />
          </span>
          <div>
            <p>资料访问范围</p>
            <strong className="text-metric">仅限本人</strong>
          </div>
        </div>
      </div>
      <div className="role-columns">
        <section className="panel">
          <PanelTitle
            title={applicant ? "申请与培养进度" : "我的党员档案"}
            action="查看档案"
            onAction={() => navigate("self-archive")}
          />
          <div className="personal-archive-summary">
            {own.profile ? (
              <>
                <div className="identity-row">
                  <span className="identity-monogram">
                    {own.profile.name[0]}
                  </span>
                  <div>
                    <h3>
                      {own.profile.name}
                      <Badge tone="red">{own.profile.stage}</Badge>
                    </h3>
                    <p>{own.profile.organization}</p>
                  </div>
                </div>
                <div className="mini-stage-rail">
                  {STAGES.map((s, i) => (
                    <div
                      className={
                        i <= STAGES.indexOf(own.profile.stage) ? "done" : ""
                      }
                      key={s}
                    >
                      <CheckCircle
                        size={17}
                        weight={
                          i <= STAGES.indexOf(own.profile.stage)
                            ? "fill"
                            : "regular"
                        }
                      />
                      <span>{s}</span>
                    </div>
                  ))}
                </div>
                <p className="minor-copy">
                  此处展示组织已登记的阶段。阶段变更由有权限的组织人员人工办理。
                </p>
              </>
            ) : (
              <Empty
                title="档案尚未关联"
                description="请联系所属支部组织员，将当前账号与本人档案明确关联。"
              />
            )}
          </div>
        </section>
        <section className="panel">
          <PanelTitle
            title="最近提交"
            action="全部材料"
            onAction={() => navigate("self-materials")}
          />
          <div className="compact-material-list">
            {own.materials.slice(0, 4).map((m) => (
              <button key={m.id} onClick={() => navigate("self-materials")}>
                <span className="file-type-icon">
                  <FileText size={21} />
                </span>
                <div>
                  <h3>{m.title}</h3>
                  <p>
                    {MATERIAL_CATEGORIES[m.category]} ·{" "}
                    {m.created_at.slice(0, 10)}
                  </p>
                </div>
                <Badge tone="blue">已提交</Badge>
              </button>
            ))}
            {!own.materials.length && (
              <Empty
                title="还没有提交记录"
                description="按组织要求上传思想汇报、学习心得等材料。"
              />
            )}
          </div>
        </section>
      </div>
      <section className="panel personal-help">
        <ShieldCheck size={30} weight="duotone" />
        <div>
          <h3>您的材料，由您和授权组织人员查阅</h3>
          <p>
            个人原件不会自动进入知识库或模型。制度咨询可使用党建智能体，业务办理请联系所属组织。
          </p>
        </div>
        <button
          className="text-button primary-text"
          onClick={() => navigate("assistant")}
        >
          制度问答
          <ArrowRight size={15} />
        </button>
      </section>
    </div>
  );
}
export function OwnArchive() {
  const { session, navigate } = useApp();
  const own = useOwnWorkspace();
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title="本人档案"
        subtitle="以组织登记为准，查看属于自己的成长记录"
        action={<Badge tone="green">仅本人可见</Badge>}
      />
      {own.error && <ErrorBox error={own.error} retry={own.reload} />}{" "}
      {own.loading ? (
        <Loading />
      ) : own.profile ? (
        <div className="own-archive">
          <div className="own-archive-top">
            <span className="large-member-avatar">{own.profile.name[0]}</span>
            <div>
              <h2>{own.profile.name}</h2>
              <div className="detail-meta">
                <Badge tone="red">{roleLabel(session.user)}</Badge>
                <Badge>{own.profile.stage}</Badge>
              </div>
            </div>
            <ShieldCheck size={30} weight="duotone" />
          </div>
          <dl className="detail-list">
            <dt>登录账号</dt>
            <dd>{session.user.username}</dd>
            <dt>所属组织</dt>
            <dd>{own.profile.organization}</dd>
            <dt>档案编号</dt>
            <dd>{own.profile.id}</dd>
            <dt>当前登记阶段</dt>
            <dd>{own.profile.stage}</dd>
            <dt>阶段登记日期</dt>
            <dd>
              {own.profile.joined || own.profile.stage_joined_on || "未登记"}
            </dd>
            <dt>组织关系状态</dt>
            <dd>{own.profile.relation || "在册"}</dd>
          </dl>
          <PanelTitle title="发展阶段" />
          <div className="stage-stepper">
            {STAGES.map((s, i) => (
              <div key={s}>
                <span
                  className={
                    i <= STAGES.indexOf(own.profile.stage)
                      ? "stage-complete"
                      : ""
                  }
                >
                  {i + 1}
                </span>
                <p>{s}</p>
              </div>
            ))}
          </div>
          <div className="inline-note">
            仅当前阶段与登记日期来自档案，不以进度条推断历史审批或培养事实。如需更正，请联系所属组织。
          </div>
          {IS_LIVE && <OwnReviews />}
          <div className="welcome-actions">
            <button
              className="button primary"
              onClick={() => navigate("self-materials")}
            >
              <UploadSimple size={17} />
              提交个人材料
            </button>
            <button
              className="button secondary"
              onClick={() => navigate("assistant")}
            >
              咨询办理要求
            </button>
          </div>
        </div>
      ) : (
        <Empty
          title="当前账号尚未关联档案"
          description="组织人员需核实账号和档案归属后关联。系统不会根据姓名自动匹配他人档案。"
          action={
            <button
              className="button secondary"
              onClick={() => navigate("assistant")}
            >
              了解材料准备要求
            </button>
          }
        />
      )}
    </section>
  );
}
export function OwnMaterials() {
  const { session } = useApp();
  const { update, notify } = useStore();
  const own = useOwnWorkspace();
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState("全部材料");
  const [upload, setUpload] = useState(false);
  const [detail, setDetail] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const submissionKey = useRef(crypto.randomUUID());
  const materialDraft = useMaterialDraft({ title: "", category: "", description: "" });
  const alive = () => getSession()?.user?.id === session.user.id;
  const filtered = own.materials.filter(
    (m) =>
      m.title.includes(query) &&
      (tab === "全部材料" || MATERIAL_CATEGORIES[m.category] === tab),
  );
  async function submit(e) {
    e.preventDefault();
    if (!own.profile) {
      setError(new Error("请先由组织员关联本人档案，再提交材料。"));
      return;
    }
    const f = new FormData(e.currentTarget);
    const file = f.get("file");
    const title = String(f.get("title") || "").trim();
    setError(null);
    if (!title) {
      setError(new Error("材料标题不能为空。"));
      return;
    }
    try {
      validateMaterialFile(file, own.maxSize, own.allowedExtensions);
    } catch (e) {
      setError(e);
      return;
    }
    setBusy(true);
    try {
      const body = {
        title,
        category: f.get("category"),
        description: String(f.get("description") || "").trim(),
        file,
        submission_key: submissionKey.current,
      };
      let material;
      if (IS_LIVE) {
        material = await roleApi.submitMaterial(body);
      } else {
        material = {
          ...body,
          id: crypto.randomUUID(),
          owner_id: session.user.id,
          profile_id: own.profile.id,
          file_name: file.name,
          file_size: file.size,
          created_at: new Date().toISOString(),
          status: "submitted",
          has_file: true,
        };
        delete material.file;
        await saveDemoFile(material.id, session.user.id, file);
      }
      if (!alive()) return;
      own.append(material);
      if (!IS_LIVE)
        update("auditEntries", (prev) => [
          newAudit(
            session.user,
            "提交个人材料",
            "personal_material",
            material.id,
          ),
          ...prev,
        ]);
      setUpload(false);
      setTab("全部材料");
      setQuery("");
      submissionKey.current = crypto.randomUUID();
      notify(
        IS_LIVE
          ? "材料已提交，等待组织人员接收"
          : "材料已保存在当前浏览器，授权组织人员可查阅。",
      );
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function download(material) {
    try {
      const blob = IS_LIVE
        ? await roleApi.ownFile(material.id)
        : await getDemoFile(material.id, session.user.id);
      if (alive()) downloadBlob(blob, material.file_name);
    } catch (e) {
      notify(e.message, "error");
    }
  }
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title="个人材料"
        subtitle="按要求提交，随时回看自己的材料与原件"
        action={
          <button
            className="button primary"
            disabled={!own.profile || own.loading}
            onClick={() => {
              materialDraft.reset();
              setUpload(true);
              setError(null);
            }}
          >
            <UploadSimple size={17} />
            提交材料
          </button>
        }
      />
      <Tabs
        items={["全部材料", ...Object.values(MATERIAL_CATEGORIES)]}
        active={tab}
        onChange={setTab}
      />
      <div className="table-toolbar">
        <SearchInput
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索我的材料标题"
        />
        <span className="toolbar-spacer" />
        <span className="muted small-text">
          {IS_LIVE ? "组织授权接收" : "原件保存在当前浏览器"}
        </span>
      </div>
      {own.error && <ErrorBox error={own.error} retry={own.reload} />}{" "}
      {!own.profile && !own.loading && !own.error && (
        <div className="inline-note">
          当前账号尚未关联本人档案，请联系所属支部组织员核对。
        </div>
      )}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>材料标题</th>
              <th>类型</th>
              <th>文件</th>
              <th>提交时间</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((m) => (
              <tr key={m.id}>
                <td>
                  <button className="file-name" onClick={() => setDetail(m)}>
                    <FileText size={22} weight="duotone" />
                    {m.title}
                  </button>
                </td>
                <td>{MATERIAL_CATEGORIES[m.category] || "其他材料"}</td>
                <td>
                  {m.file_name}
                  <small className="cell-subtext">
                    {Math.max(1, Math.ceil(m.file_size / 1024))} KB
                  </small>
                </td>
                <td>{m.created_at.slice(0, 10)}</td>
                <td>
                  <Badge tone="blue">已提交</Badge>
                </td>
                <td>
                  <button
                    className="text-button link"
                    onClick={() => setDetail(m)}
                  >
                    详情
                  </button>
                  <button
                    className="text-button link separated-action"
                    onClick={() => download(m)}
                    disabled={!IS_LIVE && !m.has_file}
                  >
                    下载原件
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {own.loading && <Loading />}
        {!filtered.length && !own.loading && (
          <Empty
            title="暂无材料记录"
            description="提交后可在这里查看，原件不会自动用于知识问答。"
          />
        )}
      </div>
      {IS_LIVE && own.total > 20 && (
        <div className="table-footer">
          <Pagination
            page={own.page}
            pages={Math.ceil(own.total / 20)}
            total={own.total}
            onChange={own.setPage}
          />
        </div>
      )}
      <div className="page-note">
        “已提交”表示材料可按权限接收，审核结果和发展阶段以组织办理记录为准。
      </div>
      {upload && (
        <Modal
          title="提交个人材料"
          wide
          flat
          onClose={() => !busy && setUpload(false)}
        >
          <form onSubmit={submit}>
            <div className="form-grid">
              <Field
                label={`选择原件（上限 ${(own.maxSize / 1024 / 1024).toFixed(0)} MB）`}
                required
                full
              >
                <input
                  name="file"
                  type="file"
                  required
                  disabled={busy}
                  onChange={(e) => materialDraft.selectFile(e.target.files?.[0] || null)}
                  accept={
                    own.allowedExtensions
                      ? own.allowedExtensions.map((e) => "." + e).join(",")
                      : ".pdf,.docx,.txt,.md,.png,.jpg,.jpeg"
                  }
                />
              </Field>
              <Field label="材料标题" required full>
                <input
                  name="title"
                  required
                  maxLength={200}
                  placeholder="例如：2026年10月思想汇报"
                  value={materialDraft.draft.title}
                  onChange={(e) => materialDraft.edit("title", e.target.value)}
                />
              </Field>
              <Field label="材料类型" full>
                <select name="category" required value={materialDraft.draft.category} onChange={(e) => materialDraft.edit("category", e.target.value)}>
                  <option value="">请选择或采用文档建议</option>
                  {Object.entries(MATERIAL_CATEGORIES).map(([v, l]) => (
                    <option value={v} key={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="说明" full>
                <textarea
                  name="description"
                  rows={3}
                  maxLength={2000}
                  placeholder="说明材料内容与提交事项，请勿填写无关第三人信息。"
                  value={materialDraft.draft.description}
                  onChange={(e) => materialDraft.edit("description", e.target.value)}
                />
              </Field>
            </div>
            <MaterialSuggestions file={materialDraft.file} maxSize={own.maxSize} allowedExtensions={own.allowedExtensions} disabled={busy} onApply={(fields) => materialDraft.apply(fields, ["title", "category", "description"])} />
            <div className="inline-note">
              <ShieldCheck size={17} />
              {IS_LIVE
                ? "原件私有保存，仅本人和授权组织人员可下载。"
                : "原件保存在当前浏览器，请妥善保管，并按组织要求提交。"}
            </div>
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <button
                type="button"
                disabled={busy}
                className="button secondary"
                onClick={() => setUpload(false)}
              >
                取消
              </button>
              <button className="button primary" disabled={busy}>
                {busy ? "正在提交…" : "确认提交"}
              </button>
            </div>
          </form>
        </Modal>
      )}
      {detail && (
        <Modal title="材料详情" onClose={() => setDetail(null)}>
          <div className="document-heading">
            <FileText size={35} />
            <div>
              <h3>{detail.title}</h3>
              <p>
                {MATERIAL_CATEGORIES[detail.category]} ·{" "}
                {detail.created_at.slice(0, 10)}
              </p>
            </div>
          </div>
          <p className="body-copy">{detail.description || "暂无补充说明"}</p>
          <div className="inline-note">
            {detail.file_name} · 已提交
            {!IS_LIVE && !detail.has_file ? " · 尚未附原件" : ""}
          </div>
          <div className="modal-actions">
            <button
              className="button secondary"
              disabled={!IS_LIVE && !detail.has_file}
              onClick={() => download(detail)}
            >
              <DownloadSimple size={16} />
              下载原件
            </button>
          </div>
        </Modal>
      )}
    </section>
  );
}
