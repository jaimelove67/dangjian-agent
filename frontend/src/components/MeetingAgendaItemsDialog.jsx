import { useState } from "react";
import { ArrowDown, ArrowUp, Plus, Trash } from "@phosphor-icons/react";
import { backend } from "../api";
import { ErrorBox, Field, Modal } from "../components";

const TYPES = [
  "学习类",
  "研究类",
  "审议类",
  "表决类",
  "部署类",
  "通报类",
  "会前准备",
  "会上安排",
  "其他",
];

function initialRows(record) {
  if (record.agendaItems?.length) {
    return record.agendaItems.map((item) => ({
      type: item.type || "学习类",
      title: item.title || "",
      reporter: item.reporter || "",
      decision_required: Boolean(item.decision_required),
    }));
  }
  return [{ type: "学习类", title: "", reporter: "", decision_required: false }];
}

export function MeetingAgendaItemsDialog({ record, onClose, onSaved }) {
  const [rows, setRows] = useState(() => initialRows(record));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  function update(index, key, value) {
    setRows((current) =>
      current.map((row, rowIndex) =>
        rowIndex === index ? { ...row, [key]: value } : row,
      ),
    );
  }

  function add() {
    setRows((current) => [
      ...current,
      { type: "学习类", title: "", reporter: "", decision_required: false },
    ]);
  }

  function remove(index) {
    setRows((current) => current.filter((_, rowIndex) => rowIndex !== index));
  }

  function move(index, delta) {
    setRows((current) => {
      const next = [...current];
      const target = index + delta;
      if (target < 0 || target >= next.length) return current;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  async function save() {
    const items = rows
      .map((row) => ({
        type: row.type,
        title: row.title.trim(),
        reporter: row.reporter.trim(),
        decision_required: row.decision_required,
      }))
      .filter((row) => row.title);
    if (!items.length) {
      setError(new Error("请至少填写一条会议议题。"));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await backend.updateMeetingAgendaItems(record.id, {
        expected_revision: record.revision,
        reason: "人工编辑会议议题条目",
        items,
      });
      onSaved(next);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="编辑会议议题条目"
      wide
      flat
      onClose={() => !busy && onClose()}
    >
      <p className="inline-note">
        议题条目由人工填写，保存后系统只整理议题单格式。系统不会根据议题自动生成表决结果、会议决议或组织结论。
      </p>
      {error && <ErrorBox error={error} />}
      <div className="meeting-item-editor">
        {rows.map((row, index) => (
          <div className="meeting-item-editor-row" key={`${index}-${row.type}`}>
            <div className="meeting-item-editor-order">
              <strong>{index + 1}</strong>
              <button
                type="button"
                className="text-button"
                aria-label="上移议题"
                disabled={busy || index === 0}
                onClick={() => move(index, -1)}
              >
                <ArrowUp size={14} />
              </button>
              <button
                type="button"
                className="text-button"
                aria-label="下移议题"
                disabled={busy || index === rows.length - 1}
                onClick={() => move(index, 1)}
              >
                <ArrowDown size={14} />
              </button>
            </div>
            <Field label="议题类型">
              <select
                value={row.type}
                disabled={busy}
                onChange={(event) => update(index, "type", event.target.value)}
              >
                {TYPES.map((type) => (
                  <option key={type}>{type}</option>
                ))}
              </select>
            </Field>
            <Field label="议题内容" full>
              <input
                value={row.title}
                disabled={busy}
                maxLength={300}
                placeholder="例如：传达学习有关文件精神"
                onChange={(event) => update(index, "title", event.target.value)}
              />
            </Field>
            <Field label="汇报人 / 承办人">
              <input
                value={row.reporter}
                disabled={busy}
                maxLength={100}
                placeholder="可选"
                onChange={(event) => update(index, "reporter", event.target.value)}
              />
            </Field>
            <label className="meeting-item-check">
              <input
                type="checkbox"
                checked={row.decision_required}
                disabled={busy}
                onChange={(event) =>
                  update(index, "decision_required", event.target.checked)
                }
              />
              需要表决或形成决议
            </label>
            <button
              type="button"
              className="text-button danger"
              disabled={busy}
              onClick={() => remove(index)}
            >
              <Trash size={14} /> 删除
            </button>
          </div>
        ))}
      </div>
      <button
        type="button"
        className="button secondary"
        disabled={busy}
        onClick={add}
      >
        <Plus size={15} /> 增加议题
      </button>
      <div className="modal-actions">
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={onClose}
        >
          取消
        </button>
        <button
          type="button"
          className="button primary"
          disabled={busy}
          onClick={save}
        >
          {busy ? "正在保存…" : "保存议题条目"}
        </button>
      </div>
    </Modal>
  );
}
