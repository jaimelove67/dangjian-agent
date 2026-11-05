import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp } from "@phosphor-icons/react";
import { backend } from "../api";
import { Badge, ErrorBox, Field, Loading, Modal } from "../components";

const LABELS = [
  ["meeting_time", "时间字段"],
  ["location", "地点字段"],
  ["host", "主持人字段"],
  ["recorder", "记录人字段"],
  ["attendance", "人数"],
];

function prepare(data) {
  const source = data.draft || data.published || data.default_schema;
  return {
    sections: (source.sections || []).map((item) => ({ ...item })),
    labels: { ...(source.labels || {}) },
  };
}

export function MeetingTemplateDialog({ orgs = [], onClose, onSaved }) {
  const [scopeOrgId, setScopeOrgId] = useState("");
  const [state, setState] = useState(null);
  const [sections, setSections] = useState([]);
  const [labels, setLabels] = useState({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState(null);
  const [message, setMessage] = useState("");

  async function load(scope = scopeOrgId) {
    setLoading(true);
    setError(null);
    try {
      const data = await backend.meetingDocumentTemplate(scope);
      setState(data);
      const prepared = prepare(data);
      setSections(prepared.sections);
      setLabels(prepared.labels);
    } catch (failure) {
      setError(failure);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load("");
  }, []);

  function updateSection(index, key, value) {
    setSections((current) =>
      current.map((item, itemIndex) =>
        itemIndex === index ? { ...item, [key]: value } : item,
      ),
    );
  }

  function move(index, delta) {
    setSections((current) => {
      const next = [...current];
      const target = index + delta;
      if (target < 0 || target >= next.length) return current;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function payload() {
    return {
      org_unit_id: scopeOrgId || undefined,
      sections,
      labels,
    };
  }

  async function saveDraft() {
    setBusy("draft");
    setError(null);
    setMessage("");
    try {
      await backend.saveMeetingDocumentTemplateDraft(payload());
      await load(scopeOrgId);
      setMessage("模板草稿已保存；发布后才会用于新会议。");
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy("");
    }
  }

  async function publish() {
    setBusy("publish");
    setError(null);
    setMessage("");
    try {
      const data = await backend.publishMeetingDocumentTemplate(payload());
      await load(scopeOrgId);
      setMessage(`已发布模板第 ${data.version} 版。`);
      onSaved?.(data);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy("");
    }
  }

  return (
    <Modal
      title="会议文书模板"
      wide
      flat
      onClose={() => !busy && onClose()}
    >
      <p className="inline-note">
        模板只控制章节标题、顺序、显示和字段名称，不允许写入脚本或任意 HTML。发布后只影响之后生成的文书，历史会议保留生成时的版本快照。
      </p>
      {error && <ErrorBox error={error} />}
      {message && <p className="inline-note">{message}</p>}
      {loading ? (
        <Loading />
      ) : (
        <>
          <div className="form-grid">
            <Field label="适用范围" full>
              <select
                value={scopeOrgId}
                disabled={Boolean(busy)}
                onChange={(event) => {
                  const next = event.target.value;
                  setScopeOrgId(next);
                  load(next);
                }}
              >
                <option value="">学校默认</option>
                {orgs.map((org) => (
                  <option key={org.id} value={org.id}>
                    {org.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <div className="meeting-template-heading">
            <strong>章节顺序</strong>
            <span>
              已发布：
              {state?.published ? (
                <Badge tone="green">第 {state.published.version} 版</Badge>
              ) : (
                <Badge tone="gray">使用上级或默认模板</Badge>
              )}
            </span>
          </div>
          <div className="meeting-template-sections">
            {sections.map((section, index) => (
              <div className="meeting-template-row" key={section.key}>
                <div className="meeting-template-order">
                  <strong>{index + 1}</strong>
                  <button
                    type="button"
                    className="text-button"
                    aria-label="上移章节"
                    disabled={Boolean(busy) || index === 0}
                    onClick={() => move(index, -1)}
                  >
                    <ArrowUp size={14} />
                  </button>
                  <button
                    type="button"
                    className="text-button"
                    aria-label="下移章节"
                    disabled={Boolean(busy) || index === sections.length - 1}
                    onClick={() => move(index, 1)}
                  >
                    <ArrowDown size={14} />
                  </button>
                </div>
                <label className="meeting-template-enabled">
                  <input
                    type="checkbox"
                    checked={section.enabled}
                    disabled={Boolean(busy) || section.key === "footer"}
                    onChange={(event) =>
                      updateSection(index, "enabled", event.target.checked)
                    }
                  />
                  显示
                </label>
                <Field label="章节标题">
                  <input
                    value={section.title}
                    disabled={Boolean(busy)}
                    maxLength={100}
                    onChange={(event) =>
                      updateSection(index, "title", event.target.value)
                    }
                  />
                </Field>
                <small className="muted">
                  {section.key === "footer"
                    ? "统一说明章节固定保留"
                    : "关闭后导出和打印中不显示"}
                </small>
              </div>
            ))}
          </div>
          <div className="meeting-template-heading">
            <strong>字段名称</strong>
          </div>
          <div className="form-grid">
            {LABELS.map(([key, label]) => (
              <Field label={label} key={key}>
                <input
                  value={labels[key] || ""}
                  disabled={Boolean(busy)}
                  maxLength={50}
                  onChange={(event) =>
                    setLabels((current) => ({
                      ...current,
                      [key]: event.target.value,
                    }))
                  }
                />
              </Field>
            ))}
          </div>
          <div className="meeting-template-preview">
            <strong>预览</strong>
            <p>
              {labels.meeting_time} · {labels.location} · {labels.host} ·{" "}
              {labels.recorder} · {labels.attendance}
            </p>
            <ol>
              {sections
                .filter((section) => section.enabled)
                .map((section) => (
                  <li key={section.key}>{section.title}</li>
                ))}
            </ol>
          </div>
          <div className="modal-actions">
            <button
              type="button"
              className="button secondary"
              disabled={Boolean(busy)}
              onClick={onClose}
            >
              关闭
            </button>
            <button
              type="button"
              className="button secondary"
              disabled={Boolean(busy)}
              onClick={saveDraft}
            >
              {busy === "draft" ? "正在保存…" : "保存草稿"}
            </button>
            <button
              type="button"
              className="button primary"
              disabled={Boolean(busy)}
              onClick={publish}
            >
              {busy === "publish" ? "正在发布…" : "发布模板"}
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}
