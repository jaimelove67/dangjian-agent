import { useEffect, useState } from "react";
import {
  Plus,
  PencilSimple,
  DownloadSimple,
  CalendarBlank,
  MapPin,
  UsersThree,
  Clock,
  FilePdf,
  Image,
  PlayCircle,
  BookOpen,
  CheckCircle,
  ArrowRight,
  Flag,
  CircleNotch,
  Trash,
} from "@phosphor-icons/react";
import { useStore } from "../store";
import { useApp } from "../app-context";
import { backend, IS_LIVE, request } from "../api";
import { deleteDemoFile, getDemoFile, saveDemoFile } from "../demo-files";
import {
  MEETING_IMAGE_ACCEPT,
  MEETING_IMAGE_LIMIT,
  meetingImageSelectionError,
} from "../meeting-images";
import {
  scopedMeetings,
  scopedOrganizations,
  ROLE_INFO,
  hasPermission,
} from "../roles";
import { roleApi } from "../role-api";
import { submitDemoMeeting } from "../role-actions";
import { newAudit } from "../role-data";
import { courses, DEPARTMENTS, organizations } from "../data";
import { meetingPayload, meetingParticipants } from "../contracts";
import {
  PageHeader,
  PanelTitle,
  Tabs,
  SearchInput,
  Select,
  Badge,
  Modal,
  Field,
  Empty,
  ErrorBox,
  Loading,
  downloadBlob,
} from "../components";
const TYPE_MAP = {
  支部大会: "branch_member_meeting",
  支委会: "branch_committee_meeting",
  党小组会: "party_group_meeting",
  党课: "party_lecture",
  组织生活会: "organizational_life_meeting",
};
const TYPE_NAMES = Object.fromEntries(
  Object.entries(TYPE_MAP).map(([k, v]) => [v, k]),
);
function normalizeMeeting(m) {
  return {
    ...m,
    date: m.scheduled_on,
    time: "",
    type: TYPE_NAMES[m.activity_type] || "其他",
    activityType: m.activity_type,
    host: m.host,
    location: m.context?.location || "待登记",
    organization: m.org_name || m.org_unit_id,
    orgId: m.org_unit_id,
    attended: (m.participants || []).filter((p) => p.attended).length,
    total: m.participants?.length || 0,
    status: m.archived_at
      ? "已归档"
      : m.review_status === "approved"
        ? "已完成"
        : m.review_status === "pending"
          ? "待审核"
          : m.review_status === "rejected"
            ? "已退回"
            : "待召开",
    agenda: m.context?.agenda || "",
    minutes: typeof m.transcript === "string" ? m.transcript : "",
    images: Array.isArray(m.context?.images)
      ? m.context.images
      : Array.isArray(m.images)
        ? m.images
        : [],
    revision: m.revision,
  };
}
function MeetingImage({ recordId, image, className = "", onClick }) {
  const { session } = useApp();
  const [state, setState] = useState({
    status: image?.data_url ? "ready" : "loading",
    url: image?.data_url || "",
  });
  useEffect(() => {
    let active = true;
    let objectUrl = "";
    if (!image?.id) {
      setState({ status: "error", url: "" });
      return () => {};
    }
    if (image.data_url) {
      setState({ status: "ready", url: image.data_url });
      return () => {};
    }
    setState({ status: "loading", url: "" });
    const ownerId = image.owner_id || recordId || session.user.id;
    const load = IS_LIVE
      ? backend.meetingImage(recordId, image.id)
      : getDemoFile(image.id, ownerId);
    load
      .then((blob) => {
        if (!active) return;
        objectUrl = URL.createObjectURL(blob);
        setState({ status: "ready", url: objectUrl });
      })
      .catch(() => {
        if (active) setState({ status: "error", url: "" });
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [recordId, image?.id, image?.owner_id, image?.data_url, session.user.id]);
  if (state.status === "loading")
    return (
      <div className={`meeting-image meeting-image-placeholder ${className}`}>
        <CircleNotch size={17} className="spin" />
        <span>加载图片</span>
      </div>
    );
  if (state.status === "error")
    return (
      <div className={`meeting-image meeting-image-placeholder ${className}`}>
        <Image size={18} />
        <span>图片读取失败</span>
      </div>
    );
  const content = (
    <img
      src={state.url}
      alt={image?.file_name || "会议现场图片"}
      loading="lazy"
    />
  );
  return onClick ? (
    <button
      type="button"
      className={`meeting-image ${className}`}
      onClick={onClick}
      aria-label={`查看${image?.file_name || "会议现场图片"}`}
    >
      {content}
    </button>
  ) : (
    <div className={`meeting-image ${className}`}>{content}</div>
  );
}
export function Meetings() {
  const { data, update, notify } = useStore();
  const { routeParams, session } = useApp();
  const [tab, setTab] = useState("会议管理");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(
    routeParams.id || data.meetings[0]?.id,
  );
  const [editing, setEditing] = useState(null);
  const [submitting, setSubmitting] = useState(null);
  const [archiving, setArchiving] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [formImages, setFormImages] = useState([]);
  const [pendingImages, setPendingImages] = useState([]);
  const [removedImages, setRemovedImages] = useState([]);
  const [imageError, setImageError] = useState("");
  const [previewImage, setPreviewImage] = useState(null);
  const [orgs, setOrgs] = useState(() =>
    IS_LIVE ? [] : scopedOrganizations(session),
  );
  const canEdit =
    hasPermission(session, "meeting.manage") &&
    session.user.role !== "school_admin";
  function clearEditor() {
    pendingImages.forEach((item) => URL.revokeObjectURL(item.preview));
    setEditing(null);
    setFormImages([]);
    setPendingImages([]);
    setRemovedImages([]);
    setImageError("");
    setPreviewImage(null);
  }
  function closeEditor() {
    if (busy) return;
    clearEditor();
  }
  function openEditor(record = {}) {
    setEditing(record);
    setFormImages(Array.isArray(record.images) ? record.images : []);
    setPendingImages([]);
    setRemovedImages([]);
    setImageError("");
    setPreviewImage(null);
    setError(null);
  }
  function chooseImages(event) {
    const files = Array.from(event.target.files || []);
    event.target.value = "";
    const message = meetingImageSelectionError(
      files,
      formImages.length + pendingImages.length,
    );
    if (message) {
      setImageError(message);
      return;
    }
    setImageError("");
    setPendingImages((prev) => [
      ...prev,
      ...files.map((file) => ({
        id: crypto.randomUUID(),
        file,
        preview: URL.createObjectURL(file),
        name: file.name,
        size: file.size,
      })),
    ]);
  }
  function removePendingImage(id) {
    setPendingImages((prev) => {
      const item = prev.find((entry) => entry.id === id);
      if (item) URL.revokeObjectURL(item.preview);
      return prev.filter((entry) => entry.id !== id);
    });
  }
  function removeExistingImage(image) {
    setFormImages((prev) => prev.filter((entry) => entry.id !== image.id));
    setRemovedImages((prev) =>
      prev.some((entry) => entry.id === image.id) ? prev : [...prev, image],
    );
  }
  async function load() {
    if (!IS_LIVE) return;
    setBusy(true);
    try {
      const [res, options] = await Promise.all([
        backend.meetings(),
        request("/meeting/org-units"),
      ]);
      const items = (res.items || []).map(normalizeMeeting);
      update("meetings", items);
      setSelected((prev) =>
        items.some((m) => m.id === prev) ? prev : items[0]?.id,
      );
      setOrgs(options.items || []);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    load();
  }, []);
  const filtered = scopedMeetings(data, session, IS_LIVE).filter(
    (m) =>
      m.title.includes(query) &&
      (tab === "课程管理"
        ? m.type === "党课"
        : tab === "记录管理"
          ? m.status !== "待召开"
          : true),
  );
  const current = filtered.find((m) => m.id === selected) || filtered[0];
  const imageCount = formImages.length + pendingImages.length;
  async function submitReview(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const reason = new FormData(e.currentTarget).get("reason").trim();
      const latest = data.meetings.find((m) => m.id === submitting.id);
      const record = IS_LIVE
        ? normalizeMeeting(
            await roleApi.meetingAction(
              submitting.id,
              "submit",
              submitting.revision,
              reason,
            ),
          )
        : submitDemoMeeting(session, latest, submitting.revision, reason);
      update("meetings", (prev) =>
        prev.map((m) => (m.id === record.id ? record : m)),
      );
      if (!IS_LIVE)
        update("auditEntries", (prev) => [
          newAudit(session.user, "提交会议纪要审核", "meeting", record.id),
          ...prev,
        ]);
      setSubmitting(null);
      notify("已提交，请由另一位授权人员审核");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  async function recordAction(action, record, reason) {
    setBusy(true);
    setError(null);
    try {
      const next = normalizeMeeting(await roleApi.meetingAction(record.id, action, record.revision, reason));
      update("meetings", prev => prev.map(item => item.id === next.id ? next : item));
      setArchiving(null);
      notify(action === "archive" ? "会议纪要已归档" : "已从原文提取纪要，请核对后提交审核");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  async function save(e) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const pending = [...pendingImages];
    const removed = [...removedImages];
    setBusy(true);
    setError(null);
    setImageError("");
    try {
      const chosen = orgs.find(
        (o) => o.id === (form.get("orgId") || editing.orgId),
      );
      if (!chosen)
        throw new Error(
          "当前账号没有可创建会议的组织，请联系管理员核对授权范围。",
        );
      const values = {
        title: form.get("title").trim(),
        date: form.get("date"),
        time: form.get("time"),
        type: form.get("type") || editing.type,
        activityType: TYPE_MAP[form.get("type") || editing.type],
        host: form.get("host").trim(),
        location: String(form.get("location") || "未登记").trim(),
        orgId: chosen.id,
        organization: chosen.name,
        agenda: form.get("agenda").trim(),
        minutes: form.get("minutes")?.trim() || "",
        attended: Number(form.get("attended") || 0),
        total: Number(form.get("total") || 0),
        ...(IS_LIVE ? {
          heldOn: form.get("held_on") || undefined,
          participants: meetingParticipants(String(form.get("participants") || "")),
        } : {}),
      };
      if (!values.title || !values.host)
        throw new Error("会议主题和主持人不能为空。");
      if (values.attended > values.total)
        throw new Error("实到人数不能大于应到人数。");
      let record = {
        ...editing,
        ...values,
        images: [...formImages],
        id: editing.id || crypto.randomUUID(),
        status: editing.status || "待召开",
        revision: (editing.revision || 0) + 1,
      };
      if (IS_LIVE) {
        const body = meetingPayload(values, editing);
        record = normalizeMeeting(
          await (editing.id
            ? backend.updateMeeting(editing.id, body)
            : backend.createMeeting(body)),
        );
        const remainingPending = [...pending];
        const remainingRemoved = [...removed];
        const imageReason = editing.id
          ? "调整会议现场图片"
          : "登记会议现场图片";
        try {
          for (const image of removed) {
            record = normalizeMeeting(
              await backend.deleteMeetingImage(
                record.id,
                image.id,
                record.revision,
                imageReason,
              ),
            );
            const index = remainingRemoved.findIndex(
              (entry) => entry.id === image.id,
            );
            if (index >= 0) remainingRemoved.splice(index, 1);
          }
          for (const image of pending) {
            record = normalizeMeeting(
              await backend.uploadMeetingImage(
                record.id,
                image.file,
                record.revision,
                imageReason,
              ),
            );
            const index = remainingPending.findIndex(
              (entry) => entry.id === image.id,
            );
            if (index >= 0) remainingPending.splice(index, 1);
          }
        } catch (err) {
          // 文字内容已经落库，保留可继续重试的图片状态，避免重复新建会议。
          update("meetings", (prev) =>
            editing.id
              ? prev.map((m) => (m.id === record.id ? record : m))
              : [record, ...prev],
          );
          setSelected(record.id);
          setEditing(record);
          setFormImages(Array.isArray(record.images) ? record.images : []);
          setPendingImages(remainingPending);
          setRemovedImages(remainingRemoved);
          setImageError(
            "会议文字内容已保存，但部分现场图片未完成，请核对后重试。",
          );
          throw err;
        }
      } else {
        const savedImages = [];
        for (const item of pending) {
          await saveDemoFile(item.id, record.id, item.file);
          savedImages.push({
            id: item.id,
            file_name: item.name,
            size: item.size,
            content_type: item.file.type || "application/octet-stream",
            owner_id: record.id,
            uploaded_at: new Date().toISOString(),
            uploaded_by: session.user.id,
          });
        }
        for (const image of removed) {
          try {
            await deleteDemoFile(image.id, image.owner_id || record.id);
          } catch {
            // 记录引用已经移除，浏览器文件清理失败不阻断本次保存。
          }
        }
        record = { ...record, images: [...formImages, ...savedImages] };
      }
      update("meetings", (prev) =>
        editing.id
          ? prev.map((m) => (m.id === editing.id ? record : m))
          : [record, ...prev],
      );
      setSelected(record.id);
      setQuery("");
      clearEditor();
      notify(
        pending.length || removed.length
          ? "会议记录及现场图片已保存"
          : "会议记录已保存",
      );
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  function exportRecord() {
    downloadBlob(
      new Blob(
        [
          `${current.title}\n\n会议类型：${current.type}\n召开时间：${current.date} ${current.time}\n召开地点：${current.location}\n主持人：${current.host}\n参会人数：${current.attended}/${current.total}\n\n会议议题\n${current.agenda}\n\n会议记录\n${current.minutes || "尚未登记"}\n\n${IS_LIVE ? "" : "本文件为工作记录，归档效力以学校制度及审核结果为准。"}`,
        ],
        { type: "text/plain;charset=utf-8" },
      ),
      `${current.title}.txt`,
    );
    notify("会议记录已导出");
  }
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title="三会一课"
        subtitle="落实组织生活制度，提升支部工作质效"
      />
      <Tabs
        items={["会议管理", "课程管理", "记录管理", "统计分析"]}
        active={tab}
        onChange={setTab}
      />
      {error && !editing && <ErrorBox error={error} retry={load} />}
      <div className="meeting-layout">
        <aside className="meeting-list-pane">
          <SearchInput
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="输入会议名称搜索"
          />
          <div className="meeting-record-list">
            {filtered.map((m) => (
              <button
                key={m.id}
                className={current?.id === m.id ? "active" : ""}
                onClick={() => setSelected(m.id)}
              >
                <h3>{m.title}</h3>
                <p>
                  {m.date} <span>·</span> {m.type}
                </p>
                <Badge>{m.status}</Badge>
              </button>
            ))}
            {!filtered.length && !busy && (
              <Empty
                title="暂无会议记录"
                description="可以新建一条会议计划。"
              />
            )}
            {busy && !editing && <Loading />}
          </div>
        </aside>
        <div className="meeting-detail">
          {tab === "统计分析" ? (
            <>
              <PanelTitle title="组织生活概况" />
              <div className="mini-stat-grid">
                {["支部大会", "支委会", "党小组会", "党课"].map((t) => (
                  <div key={t}>
                    <p>{t}</p>
                    <strong>
                      {
                        scopedMeetings(data, session, IS_LIVE).filter(
                          (m) => m.type === t,
                        ).length
                      }
                      <small> 次</small>
                    </strong>
                  </div>
                ))}
              </div>
              <div className="inline-note">
                仅统计当前已加载记录，年度频次以完整的组织生活台账为准。
              </div>
            </>
          ) : (
            <>
              <PanelTitle title="会议详情" />
              {current ? (
                <>
                  <div className="meeting-detail-actions">
                    {canEdit &&
                      ["待召开", "已退回"].includes(current.status) && (
                        <button
                          className="button secondary"
                          onClick={() => openEditor(current)}
                        >
                          <PencilSimple size={16} />
                          编辑
                        </button>
                      )}
                    <button className="button secondary" onClick={exportRecord}>
                      <DownloadSimple size={16} />
                      导出记录
                    </button>
                    {IS_LIVE && canEdit && ["待召开", "已退回"].includes(current.status) && (
                      <button className="button secondary" disabled={busy || !current.minutes?.trim()}
                        onClick={() => recordAction("generate-minutes", current, "根据已核对原始会议记录提取纪要")}>
                        提取纪要
                      </button>
                    )}
                    {canEdit &&
                      ["待召开", "已退回"].includes(current.status) && (
                        <button
                          className="button primary"
                          disabled={busy || !current.minutes?.trim()}
                          onClick={() => {
                            setSubmitting(current);
                            setError(null);
                          }}
                        >
                          提交审核
                        </button>
                      )}
                    {IS_LIVE && hasPermission(session, "meeting.archive") && current.review_status === "approved" && !current.archived_at && (
                      <button className="button primary" disabled={busy} onClick={() => { setArchiving(current); setError(null); }}>
                        确认归档
                      </button>
                    )}
                  </div>
                  {IS_LIVE && current.missing?.length > 0 && (
                    <div className="inline-note">核对提示：{current.missing.join("；")}。请核对实际情况、保存记录并提取纪要。</div>
                  )}
                  <dl className="meeting-metadata">
                    <dt>会议名称</dt>
                    <dd className="strong-text">{current.title}</dd>
                    <dt>会议类型</dt>
                    <dd>
                      <Badge tone="red">{current.type}</Badge>
                    </dd>
                    <dt>{IS_LIVE ? "计划日期" : "召开时间"}</dt>
                    <dd>
                      {current.date} <span>{current.time}</span>
                    </dd>
                    {IS_LIVE && <><dt>实际召开日期</dt><dd>{current.held_on || "待登记"}</dd></>}
                    <dt>召开地点</dt>
                    <dd>{current.location}</dd>
                    <dt>主 持 人</dt>
                    <dd>{current.host}</dd>
                    <dt>参加人数</dt>
                    <dd>
                      {current.attended} / {current.total} 人
                    </dd>
                    <dt>会议议题</dt>
                    <dd className="agenda-box">
                      {current.agenda || "尚未登记"}
                    </dd>
                    <dt>会议记录</dt>
                    <dd className="agenda-box">
                      {current.minutes || "会议尚未召开，暂无记录。"}
                    </dd>
                  </dl>
                  <div className="meeting-images-block">
                    <div className="meeting-images-heading">
                      <span>现场图片</span>
                      <span>{current.images?.length || 0} 张</span>
                    </div>
                    {current.images?.length ? (
                      <div className="meeting-image-grid">
                        {current.images.map((image) => (
                          <MeetingImage
                            key={image.id}
                            recordId={current.id}
                            image={image}
                            onClick={() =>
                              setPreviewImage({
                                recordId: current.id,
                                image,
                              })
                            }
                          />
                        ))}
                      </div>
                    ) : (
                      <p className="meeting-images-empty">
                        尚未上传现场图片
                        {canEdit && ["待召开", "已退回"].includes(current.status)
                          ? "，可在编辑会议记录时补充。"
                          : "。"}
                      </p>
                    )}
                  </div>
                  <div className="meeting-source-note">
                    <CheckCircle size={15} />
                    {current.status === "已归档"
                      ? "已归档记录只读，请保留版本。"
                      : "会议记录需经人工审核后归档。"}
                  </div>
                </>
              ) : (
                <Empty title="请选择或新建会议" />
              )}
            </>
          )}
          {canEdit && (
            <button
              className="button primary new-meeting"
              onClick={() => openEditor({})}
            >
              <Plus size={17} />
              新增会议
            </button>
          )}
        </div>
      </div>
      {submitting && (
        <Modal
          title="提交纪要审核"
          onClose={() => !busy && setSubmitting(null)}
        >
          <form onSubmit={submitReview}>
            <h3 className="review-title">{submitting.title}</h3>
            <Field label="提交说明" required>
              <textarea
                name="reason"
                required
                rows={3}
                maxLength={2000}
                placeholder="说明已核对的纪要与参会情况"
              />
            </Field>
            <div className="inline-note">
              提交后由另一位同范围授权人员独立审核，当前提交人不能审核自己的记录。
            </div>
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <button
                className="button secondary"
                type="button"
                disabled={busy}
                onClick={() => setSubmitting(null)}
              >
                取消
              </button>
              <button className="button primary" disabled={busy}>
                {busy ? "提交中…" : "确认提交审核"}
              </button>
            </div>
          </form>
        </Modal>
      )}
      {archiving && (
        <Modal title="确认会议归档" onClose={() => !busy && setArchiving(null)}>
          <form onSubmit={e => { e.preventDefault(); recordAction("archive", archiving, new FormData(e.currentTarget).get("reason").trim()); }}>
            <h3 className="review-title">{archiving.title}</h3>
            <Field label="归档确认意见" required><textarea name="reason" rows={3} required maxLength={2000} /></Field>
            <div className="inline-note">归档与审核分别办理。归档时核对当前版本、审核状态及本校电子归档效力确认；通过后记录转为只读。</div>
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <button type="button" className="button secondary" disabled={busy} onClick={() => setArchiving(null)}>取消</button>
              <button className="button primary" disabled={busy}>{busy ? "办理中…" : "确认归档"}</button>
            </div>
          </form>
        </Modal>
      )}
      {editing && (
        <Modal
          title={editing.id ? "编辑会议记录" : "新增会议"}
          wide
          onClose={closeEditor}
        >
          <form onSubmit={save}>
            <div className="form-grid">
              {IS_LIVE && (
                <div className="inline-note field full">
                  请按实际情况登记人员编号、姓名和出勤。保存原始会议记录后，使用“提取纪要”核对送审内容。
                </div>
              )}
              <Field label="会议主题" required full>
                <input
                  name="title"
                  defaultValue={editing.title}
                  placeholder="请输入会议主题"
                  maxLength={150}
                  required
                />
              </Field>
              <Field label="会议类型">
                <select
                  name="type"
                  disabled={IS_LIVE && !!editing.id}
                  defaultValue={editing.type || "支部大会"}
                >
                  {Object.keys(TYPE_MAP).map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </select>
              </Field>
              <Field label="所属组织" required>
                <select
                  name="orgId"
                  defaultValue={editing.orgId}
                  disabled={IS_LIVE && !!editing.id}
                >
                  {orgs.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="召开日期" required>
                <input
                  name="date"
                  type="date"
                  defaultValue={editing.date || "2026-10-28"}
                  required
                />
              </Field>
              {IS_LIVE && editing.id && <Field label="实际召开日期">
                <input name="held_on" type="date" defaultValue={editing.held_on || ""}
                  max={new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10)} />
              </Field>}
              <Field label="召开时间" required>
                <input
                  name="time"
                  type="time"
                  defaultValue={editing.time || "14:30"}
                  required
                  disabled={IS_LIVE}
                />
              </Field>
              <Field label="主持人" required>
                <input
                  name="host"
                  defaultValue={editing.host}
                  maxLength={40}
                  required
                />
              </Field>
              <Field label="召开地点" required>
                <input
                  name="location"
                  defaultValue={editing.location}
                  maxLength={100}
                  required
                  disabled={IS_LIVE}
                />
              </Field>
              <Field label="应到人数">
                <input
                  name="total"
                  disabled={IS_LIVE}
                  type="number"
                  min="0"
                  max="10000"
                  defaultValue={editing.total || 0}
                />
              </Field>
              <Field label="实到人数">
                <input
                  name="attended"
                  disabled={IS_LIVE}
                  type="number"
                  min="0"
                  max="10000"
                  defaultValue={editing.attended || 0}
                />
              </Field>
              <Field label="会议议题" full>
                <textarea
                  name="agenda"
                  rows={3}
                  defaultValue={editing.agenda}
                  maxLength={3000}
                  placeholder="逐项填写会议议程"
                />
              </Field>
              {IS_LIVE && <Field label="实名参会记录（每行：人员编号 | 姓名 | 出席或缺席）" full>
                <textarea name="participants" rows={4} maxLength={100000}
                  defaultValue={(editing.participants || []).map(p => `${p.participant_id} | ${p.name} | ${p.attended ? "出席" : "缺席"}`).join("\n")}
                  placeholder="填写真实参会名单；未确定时可留空，送审前须补齐。" />
              </Field>}
              <Field label="会议记录" full>
                <textarea
                  name="minutes"
                  disabled={IS_LIVE && !editing.id}
                  rows={3}
                  defaultValue={editing.minutes}
                  maxLength={10000}
                  placeholder="请根据实际会议情况填写"
                />
              </Field>
              <div className="field full">
                <span>现场图片（最多 {MEETING_IMAGE_LIMIT} 张）</span>
                <div className="meeting-image-editor">
                  {imageCount > 0 && (
                    <div className="meeting-image-grid meeting-image-edit-grid">
                      {formImages.map((image) => (
                        <div className="meeting-image-edit-item" key={image.id}>
                          <MeetingImage
                            recordId={editing.id}
                            image={image}
                          />
                          <button
                            type="button"
                            className="meeting-image-remove"
                            onClick={() => removeExistingImage(image)}
                            disabled={busy}
                            aria-label="移除现场图片"
                          >
                            <Trash size={13} />
                          </button>
                          <span className="meeting-image-name">
                            {image.file_name || "现场图片"}
                          </span>
                        </div>
                      ))}
                      {pendingImages.map((item) => (
                        <div className="meeting-image-edit-item" key={item.id}>
                          <div className="meeting-image">
                            <img src={item.preview} alt={item.name} />
                          </div>
                          <button
                            type="button"
                            className="meeting-image-remove"
                            onClick={() => removePendingImage(item.id)}
                            disabled={busy}
                            aria-label="移除待上传图片"
                          >
                            <Trash size={13} />
                          </button>
                          <span className="meeting-image-name">
                            {item.name}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                  <label
                    className={`meeting-image-upload ${
                      imageCount >= MEETING_IMAGE_LIMIT ? "disabled" : ""
                    }`}
                  >
                    <input
                      type="file"
                      multiple
                      accept={MEETING_IMAGE_ACCEPT}
                      onChange={chooseImages}
                      disabled={busy || imageCount >= MEETING_IMAGE_LIMIT}
                    />
                    <Image size={20} />
                    <span>
                      {imageCount >= MEETING_IMAGE_LIMIT
                        ? "已达到图片上限"
                        : "选择现场图片"}
                    </span>
                    <small>JPG、PNG 或 WebP，单张不超过 10 MB</small>
                  </label>
                  <div className="inline-note">
                    现场图片随会议版本留存，仅作会议记录佐证；请勿上传涉密材料。
                  </div>
                  {imageError && (
                    <p className="form-error" role="alert">
                      {imageError}
                    </p>
                  )}
                </div>
              </div>
              {IS_LIVE && editing.id && <div className="inline-note field full">
                原文按“学习要点：”“讨论共识：”“工作要求：”分行记录；组织生活会使用“查摆问题：”“批评意见：”“整改方向：”。提取只保留原文中已明确记载的内容。
              </div>}
            </div>
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <button
                type="button"
                className="button secondary"
                onClick={closeEditor}
              >
                取消
              </button>
              <button className="button primary" disabled={busy}>
                {busy ? "保存中…" : "保存会议"}
              </button>
            </div>
          </form>
        </Modal>
      )}
      {previewImage && (
        <Modal
          title={previewImage.image.file_name || "会议现场图片"}
          wide
          onClose={() => setPreviewImage(null)}
        >
          <div className="meeting-image-preview-wrap">
            <MeetingImage
              recordId={previewImage.recordId}
              image={previewImage.image}
              className="meeting-image-preview"
            />
          </div>
        </Modal>
      )}
    </section>
  );
}
export function Activities() {
  const { data, update, notify } = useStore();
  const { session } = useApp();
  const schoolSupervisor = session.user.role === "school_admin";
  const orgOptions = scopedOrganizations(session);
  const wholeSchool = ["school_admin", "system_admin"].includes(
    session.user.role,
  );
  const departmentOptions = wholeSchool
    ? DEPARTMENTS
    : [session.user.department];
  const visibleActivities = data.activities.filter(
    (a) =>
      wholeSchool ||
      (a.orgId
        ? orgOptions.some((o) => o.id === a.orgId)
        : session.user.role === "department_admin" &&
          a.organization === session.user.department),
  );
  const [tab, setTab] = useState("活动管理");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [department, setDepartment] = useState("");
  const [adding, setAdding] = useState(false);
  const [detail, setDetail] = useState(null);
  const filtered = visibleActivities.filter(
    (a) =>
      a.title.includes(query) &&
      (!status || a.status === status) &&
      (!department || a.organization === department),
  );
  function create(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const title = f.get("title").trim();
    if (!title) {
      notify("活动主题不能为空", "error");
      return;
    }
    const item = {
      id: crypto.randomUUID(),
      title,
      date: f.get("date"),
      location: f.get("location").trim(),
      organization: f.get("organization"),
      orgId:
        wholeSchool || session.user.role === "department_admin"
          ? undefined
          : session.user.org_unit_id,
      description: f.get("description").trim(),
      participants: 0,
      status: "报名中",
      cover: 1,
    };
    update("activities", (prev) => [item, ...prev]);
    setAdding(false);
    setTab("活动管理");
    setStatus("");
    setDepartment("");
    setQuery("");
    notify("活动发布记录已保存");
  }
  function enroll(item) {
    if (data.enrollments.includes(item.id)) return;
    update("enrollments", (prev) => [...prev, item.id]);
    update("activities", (prev) =>
      prev.map((a) =>
        a.id === item.id ? { ...a, participants: a.participants + 1 } : a,
      ),
    );
    setDetail((prev) =>
      prev ? { ...prev, participants: prev.participants + 1 } : null,
    );
    notify("报名成功，活动已加入我的活动");
  }
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title="主题党日"
        subtitle="让组织生活有温度，让红色精神有传承"
        action={
          !schoolSupervisor && (
            <button className="button primary" onClick={() => setAdding(true)}>
              <Plus size={18} />
              发起活动
            </button>
          )
        }
      />
      <Tabs
        items={["活动管理", "活动签到", "活动统计"]}
        active={tab}
        onChange={setTab}
      />
      <div className="table-toolbar">
        <SearchInput
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索活动主题"
        />
        <Select
          label="活动状态"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="">全部状态</option>
          {["报名中", "进行中", "已结束"].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </Select>
        <Select
          label="所属学院"
          value={department}
          onChange={(e) => setDepartment(e.target.value)}
        >
          <option value="">全部学院</option>
          {departmentOptions.map((d) => (
            <option key={d}>{d}</option>
          ))}
        </Select>
      </div>
      {tab === "活动统计" ? (
        <div className="activity-stats">
          <div>
            <Flag size={30} />
            <strong>{visibleActivities.length}</strong>
            <p>活动总数</p>
          </div>
          <div>
            <UsersThree size={30} />
            <strong>
              {visibleActivities.reduce((n, a) => n + a.participants, 0)}
            </strong>
            <p>累计参与人次</p>
          </div>
          <div>
            <CheckCircle size={30} />
            <strong>
              {
                visibleActivities.filter((a) => data.enrollments.includes(a.id))
                  .length
              }
            </strong>
            <p>我的报名</p>
          </div>
        </div>
      ) : (
        <div className="activity-list">
          {filtered.map((a) => (
            <div className="activity-row" key={a.id}>
              <button
                className="activity-image"
                onClick={() => setDetail(a)}
                aria-label={`查看${a.title}`}
              >
                <img
                  src={`/assets/activity-${a.cover}.png`}
                  alt="主题党日活动现场"
                />
              </button>
              <button className="activity-info" onClick={() => setDetail(a)}>
                <h3>{a.title}</h3>
                <p>
                  <CalendarBlank size={14} />
                  {a.date}
                  <span>·</span>
                  {a.organization}
                </p>
                <span className="activity-location">
                  <MapPin size={13} />
                  {a.location}
                </span>
              </button>
              <div className="activity-enroll">
                <span>
                  参与 <b>{a.participants}</b> 人
                </span>
                <Badge>{a.status}</Badge>
                {tab === "活动签到" && !schoolSupervisor && (
                  <button
                    className="text-button link"
                    onClick={() => enroll(a)}
                    disabled={
                      a.status === "已结束" || data.enrollments.includes(a.id)
                    }
                  >
                    {data.enrollments.includes(a.id) ? "已报名" : "报名参与"}
                  </button>
                )}
              </div>
              <button
                className="icon-button"
                onClick={() => setDetail(a)}
                aria-label="查看活动详情"
              >
                <ArrowRight size={18} />
              </button>
            </div>
          ))}
          {!filtered.length && <Empty />}
        </div>
      )}
      <div className="page-note">报名记录保存在当前浏览器，请按组织要求确认参会安排。</div>
      {adding && (
        <Modal title="发起主题党日活动" wide onClose={() => setAdding(false)}>
          <form onSubmit={create}>
            <div className="form-grid">
              <Field label="活动主题" required full>
                <input
                  name="title"
                  required
                  maxLength={120}
                  placeholder="为活动起一个名字"
                />
              </Field>
              <Field label="活动日期" required>
                <input
                  name="date"
                  type="date"
                  defaultValue="2026-10-28"
                  required
                />
              </Field>
              <Field label="组织单位">
                <select name="organization">
                  {departmentOptions.map((d) => (
                    <option key={d}>{d}</option>
                  ))}
                </select>
              </Field>
              <Field label="活动地点" required full>
                <input
                  name="location"
                  required
                  maxLength={100}
                  placeholder="请输入活动地点"
                />
              </Field>
              <Field label="活动内容" full>
                <textarea
                  name="description"
                  rows={4}
                  maxLength={2000}
                  placeholder="介绍活动目的、安排和参与要求"
                />
              </Field>
            </div>
            <div className="modal-actions">
              <button
                type="button"
                className="button secondary"
                onClick={() => setAdding(false)}
              >
                取消
              </button>
              <button className="button primary">发布活动</button>
            </div>
          </form>
        </Modal>
      )}
      {detail && (
        <Modal title="活动详情" wide onClose={() => setDetail(null)}>
          <img
            className="activity-detail-image"
            src={`/assets/activity-${detail.cover}.png`}
            alt="主题党日活动现场"
          />
          <h2 className="activity-detail-title">{detail.title}</h2>
          <div className="detail-meta">
            <span>
              <CalendarBlank size={15} />
              {detail.date}
            </span>
            <span>
              <MapPin size={15} />
              {detail.location}
            </span>
            <Badge>{detail.status}</Badge>
          </div>
          <p className="body-copy">{detail.description}</p>
          <div className="modal-actions">
            <span>{detail.participants} 人参与</span>
            {!schoolSupervisor && (
              <button
                className="button primary"
                disabled={
                  detail.status === "已结束" ||
                  data.enrollments.includes(detail.id)
                }
                onClick={() => enroll(detail)}
              >
                {data.enrollments.includes(detail.id)
                  ? "已报名"
                  : detail.status === "已结束"
                    ? "活动已结束"
                    : "报名参与"}
              </button>
            )}
          </div>
        </Modal>
      )}
    </section>
  );
}
export function Learning() {
  const { data, update, notify } = useStore();
  const [tab, setTab] = useState(IS_LIVE ? "学习计划" : "学习课程");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [course, setCourse] = useState(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState(null);
  const [plans, setPlans] = useState([]);
  useEffect(() => {
    if (IS_LIVE)
      request("/study/plans?year=2026")
        .then((res) => setPlans(res.items || res.plans || []))
        .catch(setError);
  }, []);
  const filtered = courses.filter(
    (c) => c.title.includes(query) && (!category || c.category === category),
  );
  const filteredPlans = plans.filter(p => (p.title || p.topic || "").includes(query));
  function open(c) {
    setCourse(c);
    setNote(data.learning[c.id]?.note || "");
  }
  function saveNote(complete) {
    update("learning", (prev) => ({
      ...prev,
      [course.id]: {
        ...prev[course.id],
        note,
        completed: complete || prev[course.id]?.completed,
        date: "2026-10-23",
        title: course.title,
      },
    }));
    notify(complete ? "本次学习已完成，学习记录已更新" : "学习笔记已保存");
    if (complete) setCourse(null);
  }
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title="学习教育"
        subtitle="在常学常新中加强理论修养，在真学真信中坚定理想信念"
      />
      <Tabs
        items={IS_LIVE ? ["学习计划"] : ["学习课程", "学习计划", "学习情况", "在线考试", "学习积分"]}
        active={tab}
        onChange={setTab}
      />
      {error && <ErrorBox error={error} />}
      <div className="table-toolbar">
        <SearchInput
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={IS_LIVE ? "搜索已加载学习计划" : "请输入课程名称"}
        />
        {!IS_LIVE && <Select
          label="课程类型"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        >
          <option value="">全部类型</option>
          {["理论学习", "党史学习", "业务培训", "党性教育"].map((t) => (
            <option key={t}>{t}</option>
          ))}
        </Select>}
        <span className="toolbar-spacer" />
        <span className="muted small-text">
          {IS_LIVE ? "中心组学习计划" : "共 8 门精选学习专题"}
        </span>
      </div>
      {IS_LIVE ? (
        <div className="learning-live-list">
          {filteredPlans.map((p) => (
            <div className="learning-plan" key={p.id}>
              <BookOpen size={28} />
              <div>
                <h3>{p.title || p.topic || "中心组学习计划"}</h3>
                <p>
                  {p.year} · {p.status || "已登记"}
                </p>
              </div>
            </div>
          ))}
          {!filteredPlans.length && (
            <Empty
              title={query ? "暂无匹配的学习计划" : "暂无授权学习计划"}
              description={query ? "请调整计划名称后重试。" : "请先在年度学习计划中编制学习安排。"}
            />
          )}
        </div>
      ) : tab === "学习课程" ? (
        <div className="course-grid">
          {filtered.map((c) => (
            <button className="course-card" key={c.id} onClick={() => open(c)}>
              <div className="course-cover">
                <img src={`/assets/course-${c.cover}.png`} alt={c.title} />
                <span className="course-category">{c.category}</span>
                <span className="course-play">
                  <BookOpen size={18} weight="fill" />
                </span>
                {data.learning[c.id]?.completed && (
                  <span className="course-complete">
                    <CheckCircle size={14} weight="fill" />
                    已学完
                  </span>
                )}
              </div>
              <h3>{c.title}</h3>
              <p>{c.subtitle}</p>
              <div className="course-meta">
                <span>
                  <Clock size={12} />
                  {c.minutes}分钟
                </span>
                <span>{c.students}人学习</span>
              </div>
            </button>
          ))}
          {!filtered.length && <Empty />}
        </div>
      ) : tab === "学习计划" ? (
        <div className="learning-plan-list">
          {courses.slice(0, 3).map((c, i) => (
            <div className="learning-plan" key={c.id}>
              <div className="learning-plan-index">0{i + 1}</div>
              <div>
                <h3>{c.title}</h3>
                <p>2026年10月学习计划 · 理论学习与交流研讨</p>
              </div>
              <Badge>
                {data.learning[c.id]?.completed ? "已完成" : "进行中"}
              </Badge>
              <button className="button secondary" onClick={() => open(c)}>
                开始学习
              </button>
            </div>
          ))}
        </div>
      ) : tab === "学习情况" || tab === "学习积分" ? (
        <div className="learning-records">
          <div className="mini-stat-grid">
            <div>
              <p>已完成专题</p>
              <strong>
                {Object.values(data.learning).filter((l) => l.completed).length}
              </strong>
            </div>
            <div>
              <p>已保存笔记</p>
              <strong>
                {Object.values(data.learning).filter((l) => l.note).length}
              </strong>
            </div>
            <div>
              <p>学习积分</p>
              <strong>
                {Object.values(data.learning).filter((l) => l.completed)
                  .length * 10}
              </strong>
            </div>
          </div>
          {Object.entries(data.learning).map(([id, l]) => (
            <div className="learning-plan" key={id}>
              <BookOpen size={25} />
              <div>
                <h3>{l.title}</h3>
                <p>
                  {l.date} · {l.note ? "已记录学习笔记" : "暂无笔记"}
                </p>
              </div>
              <Badge>{l.completed ? "已完成" : "进行中"}</Badge>
              <button
                className="text-button link"
                onClick={() => open(courses.find((c) => String(c.id) === id))}
              >
                继续学习
              </button>
            </div>
          ))}
          {!Object.keys(data.learning).length && (
            <Empty
              title="从第一门专题开始"
              description="学习并保存笔记后，可在这里回顾学习记录。"
            />
          )}
        </div>
      ) : (
        <div className="organization-guidance">
          <BookOpen size={43} weight="duotone" />
          <h3>考试安排待发布</h3>
          <p>
            在线测评暂不可用，请按学校发布的考试安排参加学习测评。
          </p>
        </div>
      )}
      <div className="page-note">
        {!IS_LIVE && "当前提供专题阅读和学习笔记，视频资源暂不可用。"}
      </div>
      {course && (
        <Modal title="专题学习" wide onClose={() => setCourse(null)}>
          <div className="course-study-hero">
            <img
              src={`/assets/course-${course.cover}.png`}
              alt={course.title}
            />
            <div>
              <Badge tone="red">{course.category}</Badge>
              <h2>{course.title}</h2>
              <p>{course.subtitle}</p>
            </div>
          </div>
          <div className="reading-material">
            <h3>学习导读</h3>
            <p>{course.content}</p>
            <div className="inline-note">
              学习内容以学校发布的课程资源和现行制度为准。
            </div>
          </div>
          <Field label="我的学习笔记">
            <textarea
              rows={5}
              maxLength={5000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="记录学习收获、思考与行动计划…"
            />
          </Field>
          <div className="modal-actions">
            <button
              className="button secondary"
              onClick={() => saveNote(false)}
            >
              保存笔记
            </button>
            <button className="button primary" onClick={() => saveNote(true)}>
              <CheckCircle size={17} />
              完成本次学习
            </button>
          </div>
        </Modal>
      )}
    </section>
  );
}
