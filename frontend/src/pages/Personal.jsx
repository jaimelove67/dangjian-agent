import { useEffect, useRef, useState } from "react";
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
  Eye,
  WarningCircle,
  ArrowsClockwise,
} from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE, getSession } from "../api";
import { formatBusinessTime } from "../business-time";
import { roleApi } from "../role-api";
import { useOwnWorkspace } from "../role-hooks";
import { isSelfService, roleLabel } from "../roles";
import { MATERIAL_CATEGORIES, newAudit } from "../role-data";
import { saveDemoFile, getDemoFile } from "../demo-files";
import { validateMaterialFile } from "../material-validation";
import { STAGES } from "../data";
import { OwnReviews } from "../components/OwnReviews";
import { HomeLearning } from "../components/HomeLearning";
import { PublicationsPanel } from "../components/PublicationsPanel";
import { HomeBanner, HomeAssistant, OwnHomeTasks, OwnHomeArchive } from "../components/HomeWorkspace";
import { MaterialSuggestions, useMaterialDraft } from "../components/MaterialSuggestions";
import { MemberInfoSelfSection } from "./MemberInfo";
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

function previewKind(blob, fileName = "") {
  const mime = String(blob?.type || "").split(";")[0].toLowerCase();
  const extension = fileName.toLowerCase().split(".").pop();
  if (mime === "application/pdf" || extension === "pdf") return "pdf";
  if (mime.startsWith("image/") || ["png", "jpg", "jpeg", "gif", "webp"].includes(extension)) return "image";
  if (mime.startsWith("text/") || ["txt", "md", "csv", "json"].includes(extension)) return "text";
  return "unsupported";
}

function previewKindLabel(kind) {
  return { pdf: "PDF", image: "图片", text: "文本" }[kind] || "不可在线预览";
}

function materialBadge(material, viewed) {
  if (material.review_status === "returned")
    return { label: "已退回", tone: "red" };
  if (material.review_status === "approved")
    return { label: "审核通过", tone: "green" };
  if (material.has_file === false)
    return { label: "原件待提交", tone: "orange" };
  if (viewed) return { label: "组织已查阅", tone: "green" };
  return { label: "已提交", tone: "blue" };
}

function MaterialReviewList({ reviews }) {
  if (!reviews?.length)
    return <p className="inline-note">尚未审核，等待支部书记办理。</p>;
  return (
    <ul className="material-review-list">
      {reviews.map((review) => (
        <li key={review.id}>
          <div className="material-review-item-head">
            <Badge tone={review.decision === "approved" ? "green" : "red"}>
              {review.decision === "approved" ? "审核通过" : "已退回"}
            </Badge>
            <small>
              {formatBusinessTime(review.created_at)} ·{" "}
              {review.reviewer_name || "审核人待核对"}
            </small>
          </div>
          <p>{review.opinion || "未填写审核意见"}</p>
        </li>
      ))}
    </ul>
  );
}

export function PersonalHome() {
  const { session, navigate } = useApp();
  const { data } = useStore();
  const own = useOwnWorkspace();
  const applicant = session.user.role === "applicant";
  const identity = `${session.user.tenant_id}:${session.user.id}`;
  return <div className="home-workspace personal-home">
    <HomeBanner title="我的党建空间" personal description={own.profile?.organization || roleLabel(session.user)} stage={own.profile?.stage} />
    {own.error && <ErrorBox error={own.error} retry={own.reload} />}
    <div className="home-primary-grid">
      <div className="home-side-stack home-member-main">
        <PublicationsPanel key={identity} limit={5} />
        <section className="panel home-materials">
          <PanelTitle title="我的材料" action="全部材料" onAction={() => navigate("self-materials")} />
          <div className="home-material-actions"><span>个人提交记录 · {own.loading || own.error ? "—" : own.total} 份</span><button className="button secondary" onClick={() => navigate("self-materials")}><UploadSimple size={16} />提交个人材料</button></div>
          {own.loading ? <Loading /> : own.materials.length ? <div className="table-scroll"><table><thead><tr><th>材料名称</th><th>来源</th><th>提交时间</th><th>状态</th></tr></thead><tbody>{own.materials.slice(0, 3).map(material => <tr key={material.id}><td><button className="text-button link" onClick={() => navigate("self-materials")}>{material.title}</button></td><td>个人提交</td><td>{material.created_at?.slice(0, 10) || "—"}</td><td>{(() => { const viewed = material.last_viewed_at || (!IS_LIVE && data.materialReceipts.some((receipt) => receipt.material_id === material.id)); const state = materialBadge(material, viewed); return <Badge tone={state.tone}>{state.label}</Badge>; })()}</td></tr>)}</tbody></table></div> : !own.error && <Empty title="暂无个人提交记录" description="请按所属组织要求提交个人材料。" />}
          <p className="home-privacy"><ShieldCheck size={15} />本人材料由本人及授权组织人员查阅。</p>
        </section>
      </div>
      <div className="home-side-stack home-member-sidebar">
        <HomeLearning key={`learning:${identity}`} />
        <OwnHomeTasks key={identity} materials={own.materials} />
        <OwnHomeArchive profile={own.profile} loading={own.loading} applicant={applicant} />
        <HomeAssistant />
      </div>
    </div>
  </div>;
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
          <MemberInfoSelfSection profile={own.profile} />
          <PanelTitle title="发展阶段" />
          {own.profile.stage === "取消预备党员资格" ? (
            <div className="inline-note development-terminal-note">
              该档案已办理取消预备党员资格，发展阶段终止；已有记录继续保留。
            </div>
          ) : (
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
          )}
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
  const { data, update, notify } = useStore();
  const own = useOwnWorkspace();
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState("全部材料");
  const [upload, setUpload] = useState(false);
  const [detail, setDetail] = useState(null);
  const [filePreview, setFilePreview] = useState({ status: "idle" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [reviewHistory, setReviewHistory] = useState(null);
  const [reviewLoading, setReviewLoading] = useState(false);
  const [resubmitFrom, setResubmitFrom] = useState(null);
  const submissionKey = useRef(crypto.randomUUID());
  const materialDraft = useMaterialDraft({ title: "", category: "", description: "" });
  const alive = () => getSession()?.user?.id === session.user.id;
  async function readMaterialFile(material) {
    return IS_LIVE
      ? roleApi.ownFile(material.id)
      : getDemoFile(material.id, session.user.id);
  }
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    if (!detail) {
      setFilePreview({ status: "idle" });
      return () => {};
    }
    if (!IS_LIVE && !detail.has_file) {
      setFilePreview({ status: "missing" });
      return () => {};
    }
    setFilePreview({ status: "loading" });
    readMaterialFile(detail)
      .then(async (blob) => {
        if (!active) return;
        const kind = previewKind(blob, detail.file_name);
        if (kind === "text") {
          const text = await blob.text();
          if (active) setFilePreview({ status: "ready", kind, text });
          return;
        }
        if (kind === "pdf" || kind === "image") {
          objectUrl = URL.createObjectURL(blob);
          setFilePreview({ status: "ready", kind, url: objectUrl });
          return;
        }
        setFilePreview({ status: "unsupported", kind });
      })
      .catch((error) => {
        if (active)
          setFilePreview({
            status: "error",
            message: error?.message || "文件读取失败，请下载原件查看。",
          });
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [detail, session.user.id]);
  useEffect(() => {
    let active = true;
    if (!detail) {
      setReviewHistory(null);
      setReviewLoading(false);
      return () => {};
    }
    if (!IS_LIVE) {
      const reviews = (data.materialReviews || []).filter(
        (review) => review.material_id === detail.id,
      );
      const prior = detail.previous_material_id
        ? data.personalMaterials.find(
            (material) => material.id === detail.previous_material_id,
          )
        : null;
      setReviewHistory({
        reviews,
        previous_material: prior
          ? {
              ...prior,
              reviews: (data.materialReviews || []).filter(
                (review) => review.material_id === prior.id,
              ),
            }
          : null,
      });
      return () => {};
    }
    setReviewLoading(true);
    setReviewHistory(null);
    roleApi
      .ownMaterialReviews(detail.id)
      .then((value) => {
        if (!active) return;
        setReviewHistory(value);
        if (value?.material)
          setDetail((prev) =>
            prev && prev.id === value.material.id
              ? { ...prev, ...value.material }
              : prev,
          );
      })
      .catch(() => {
        if (active)
          setReviewHistory({
            reviews: [],
            previous_material: null,
            error: "暂时无法读取审核记录，请刷新后重试。",
          });
      })
      .finally(() => {
        if (active) setReviewLoading(false);
      });
    return () => {
      active = false;
    };
  }, [detail?.id, session.user.id]);
  const filtered = own.materials.filter(
    (m) =>
      m.title.includes(query) &&
      (tab === "全部材料" || MATERIAL_CATEGORIES[m.category] === tab),
  );
  function lastViewedAt(m) {
    if (IS_LIVE) return m.last_viewed_at || "";
    return (
      data.materialReceipts
        .filter((receipt) => receipt.material_id === m.id)
        .map((receipt) => receipt.viewed_at)
        .sort()
        .at(-1) || ""
    );
  }
  function viewedCount(m) {
    if (IS_LIVE) return Number(m.viewer_count) || 0;
    return data.materialReceipts.filter((receipt) => receipt.material_id === m.id)
      .length;
  }
  function materialState(m) {
    return materialBadge(m, lastViewedAt(m));
  }
  function startResubmit(material) {
    materialDraft.reset();
    materialDraft.edit("title", material.title);
    materialDraft.edit("category", material.category);
    materialDraft.edit("description", material.description || "");
    setResubmitFrom(material);
    setDetail(null);
    setUpload(true);
    setError(null);
  }
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
        previous_material_id: resubmitFrom?.id,
      };
      let material;
      if (IS_LIVE) {
        material = await roleApi.submitMaterial(body);
      } else {
        material = {
          ...body,
          id: crypto.randomUUID(),
          owner_id: session.user.id,
          tenant_id: session.user.tenant_id,
          profile_id: own.profile.id,
          file_name: file.name,
          file_size: file.size,
          created_at: new Date().toISOString(),
          status: "submitted",
          review_status: "pending",
          review_note: "",
          reviewed_at: null,
          reviewer_name: "",
          previous_material_id: resubmitFrom?.id || null,
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
      setResubmitFrom(null);
      setTab("全部材料");
      setQuery("");
      submissionKey.current = crypto.randomUUID();
      notify(
        IS_LIVE
          ? resubmitFrom
            ? "材料已重新提交，前次记录和审核意见保留"
            : "材料已提交，等待组织人员接收"
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
      const blob = await readMaterialFile(material);
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
              setResubmitFrom(null);
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
        <button
          type="button"
          className="button secondary"
          disabled={own.loading}
          onClick={own.reload}
        >
          <ArrowsClockwise size={16} />
          刷新
        </button>
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
                  <Badge tone={materialState(m).tone}>
                    {materialState(m).label}
                  </Badge>
                  {(m.reviewed_at || lastViewedAt(m)) && (
                    <small className="cell-subtext">
                      {formatBusinessTime(m.reviewed_at || lastViewedAt(m))}
                    </small>
                  )}
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
                  {m.review_status === "returned" && (
                    <button
                      className="text-button link separated-action"
                      onClick={() => startResubmit(m)}
                    >
                      修改重交
                    </button>
                  )}
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
        个人材料由所属支部组织人员查阅、支部书记审核；退回后可修改重交，前次记录和审核意见继续保留。审核结论不改变党员发展阶段。
      </div>
      {upload && (
        <Modal
          title={resubmitFrom ? "修改重交个人材料" : "提交个人材料"}
          wide
          flat
          onClose={() => {
            if (busy) return;
            setUpload(false);
            setResubmitFrom(null);
          }}
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
                ? resubmitFrom
                  ? "本次重交会生成新的材料记录，前次记录和审核意见继续保留。"
                  : "原件私有保存，仅本人和授权组织人员可下载。"
                : "原件保存在当前浏览器，请妥善保管，并按组织要求提交。"}
            </div>
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <button
                type="button"
                disabled={busy}
                className="button secondary"
                onClick={() => {
                  setUpload(false);
                  setResubmitFrom(null);
                }}
              >
                取消
              </button>
              <button className="button primary" disabled={busy}>
                {busy ? "正在提交…" : resubmitFrom ? "确认重交" : "确认提交"}
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
          {detail.review_status === "returned" && (
            <div className="material-returned-note" role="alert">
              <WarningCircle size={18} />
              <div>
                <strong>材料已退回</strong>
                <p>{detail.review_note || "请按组织意见修改后重新提交。"}</p>
              </div>
            </div>
          )}
          <div className="material-progress" aria-label="办理进度">
            <div className="material-progress-head">
              <div>
                <Clock size={17} />
                <strong>办理进度</strong>
              </div>
              <Badge tone={materialState(detail).tone}>
                当前环节：{materialState(detail).label}
              </Badge>
            </div>
            <ol className="material-progress-steps">
              <li className="done">
                <span className="material-progress-dot" />
                <div>
                  <strong>已提交</strong>
                  <small>{formatBusinessTime(detail.created_at)}</small>
                </div>
              </li>
              <li className={lastViewedAt(detail) ? "done" : "current"}>
                <span className="material-progress-dot" />
                <div>
                  <strong>组织查阅</strong>
                  <small>
                    {lastViewedAt(detail)
                      ? `${formatBusinessTime(lastViewedAt(detail))} · 已查阅 ${Math.max(1, viewedCount(detail))} 次`
                      : "待所属支部组织人员查阅"}
                  </small>
                </div>
              </li>
              <li
                className={
                  detail.review_status === "returned"
                    ? "error"
                    : detail.review_status === "approved"
                      ? "done"
                      : "current"
                }
              >
                <span className="material-progress-dot" />
                <div>
                  <strong>支部书记审核</strong>
                  <small>
                    {detail.review_status === "approved"
                      ? `审核通过 · ${formatBusinessTime(detail.reviewed_at)}${detail.reviewer_name ? ` · ${detail.reviewer_name}` : ""}`
                      : detail.review_status === "returned"
                        ? `已退回 · ${formatBusinessTime(detail.reviewed_at)}${detail.reviewer_name ? ` · ${detail.reviewer_name}` : ""}`
                        : lastViewedAt(detail)
                          ? "待支部书记审核"
                          : "待组织查阅后审核"}
                  </small>
                </div>
              </li>
            </ol>
            <p className="inline-note">
              负责查阅组织：{own.profile?.organization || "—"}。
            </p>
          </div>
          <div className="material-review-records" aria-label="审核记录">
            <div className="material-review-records-title">
              <FileText size={17} />
              <strong>审核记录</strong>
            </div>
            {reviewLoading ? (
              <Loading />
            ) : reviewHistory?.error ? (
              <p className="inline-note">{reviewHistory.error}</p>
            ) : (
              <MaterialReviewList reviews={reviewHistory?.reviews} />
            )}
            {reviewHistory?.previous_material && (
              <div className="material-previous">
                <strong>前次提交：{reviewHistory.previous_material.title}</strong>
                <small>
                  {formatBusinessTime(reviewHistory.previous_material.created_at)} ·{" "}
                  {reviewHistory.previous_material.review_status === "returned"
                    ? "已退回"
                    : reviewHistory.previous_material.review_status === "approved"
                      ? "审核通过"
                      : "已提交"}
                </small>
                <MaterialReviewList reviews={reviewHistory.previous_material.reviews} />
              </div>
            )}
            <p className="inline-note">
              个人材料不进入发展材料核验；审核结论不改变党员发展阶段。
            </p>
          </div>
          <div className="material-preview" aria-label="文件预览">
            <div className="material-preview-header">
              <div className="material-preview-title">
                <Eye size={16} />
                <strong>文件预览</strong>
              </div>
              {filePreview.status === "ready" && (
                <span className="material-preview-type">
                  {previewKindLabel(filePreview.kind)}
                </span>
              )}
            </div>
            {filePreview.status === "loading" && (
              <div className="material-preview-state" role="status">
                <span className="material-preview-loader" />
                <p>正在加载文件预览…</p>
              </div>
            )}
            {filePreview.status === "missing" && (
              <div className="material-preview-state">
                <WarningCircle size={22} />
                <p>当前记录未附可读取的原件</p>
                <small>请重新选择文件提交后查看预览。</small>
              </div>
            )}
            {filePreview.status === "error" && (
              <div className="material-preview-state">
                <WarningCircle size={22} />
                <p>暂时无法加载预览</p>
                <small>{filePreview.message}</small>
              </div>
            )}
            {filePreview.status === "unsupported" && (
              <div className="material-preview-state">
                <FileText size={22} />
                <p>当前文件类型暂不支持在线预览</p>
                <small>请下载原件后使用本地应用查看。</small>
              </div>
            )}
            {filePreview.status === "ready" && filePreview.kind === "pdf" && (
              <div className="material-preview-viewer pdf">
                <iframe
                  src={filePreview.url}
                  title={`${detail.file_name}预览`}
                />
              </div>
            )}
            {filePreview.status === "ready" && filePreview.kind === "image" && (
              <div className="material-preview-viewer image">
                <img src={filePreview.url} alt={`${detail.file_name}预览`} />
              </div>
            )}
            {filePreview.status === "ready" && filePreview.kind === "text" && (
              <div className="material-preview-viewer text">
                <pre>{filePreview.text}</pre>
              </div>
            )}
          </div>
          <div className="inline-note">
            {detail.file_name} ·{" "}
            {lastViewedAt(detail)
              ? `组织已查阅 ${formatBusinessTime(lastViewedAt(detail))}`
              : "已提交，等待组织查阅"}
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
            {detail.review_status === "returned" && (
              <button
                className="button primary"
                onClick={() => startResubmit(detail)}
              >
                <UploadSimple size={16} />
                修改重交
              </button>
            )}
          </div>
        </Modal>
      )}
    </section>
  );
}
