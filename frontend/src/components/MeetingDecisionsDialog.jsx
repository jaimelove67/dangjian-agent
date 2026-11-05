import { useState } from "react";
import { PencilSimple, Plus, Trash } from "@phosphor-icons/react";
import { backend } from "../api";
import { ErrorBox, Field, Modal } from "../components";

const RESULTS = [
  ["approved", "同意"],
  ["principled", "原则同意"],
  ["rejected", "不同意"],
  ["not_voted", "未表决"],
];

function initialRows(record) {
  if (record.decisions?.length) {
    return record.decisions.map((item) => ({
      title: item.title || "",
      result: item.result || "not_voted",
      agree_count: item.agree_count ?? 0,
      oppose_count: item.oppose_count ?? 0,
      abstain_count: item.abstain_count ?? 0,
      note: item.note || "",
    }));
  }
  return [
    {
      title: "",
      result: "not_voted",
      agree_count: 0,
      oppose_count: 0,
      abstain_count: 0,
      note: "",
    },
  ];
}

export function MeetingDecisionsDialog({ record, onClose, onSaved }) {
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
      {
        title: "",
        result: "not_voted",
        agree_count: 0,
        oppose_count: 0,
        abstain_count: 0,
        note: "",
      },
    ]);
  }

  function remove(index) {
    setRows((current) => current.filter((_, rowIndex) => rowIndex !== index));
  }

  async function save() {
    const decisions = rows
      .map((row) => ({
        title: row.title.trim(),
        result: row.result,
        agree_count: Number(row.agree_count) || 0,
        oppose_count: Number(row.oppose_count) || 0,
        abstain_count: Number(row.abstain_count) || 0,
        note: row.note.trim(),
      }))
      .filter((row) => row.title);
    setBusy(true);
    setError(null);
    try {
      const next = await backend.updateMeetingDecisions(record.id, {
        expected_revision: record.revision,
        reason: "人工登记会议决议和表决结果",
        decisions,
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
      title="编辑决议与表决"
      wide
      flat
      onClose={() => !busy && onClose()}
    >
      <p className="inline-note">
        决议和票数由组织人员根据真实会议情况填写，系统不自动计算结果，也不根据会议文本推断表决结论。
      </p>
      {error && <ErrorBox error={error} />}
      <div className="meeting-decision-editor">
        {rows.map((row, index) => (
          <div className="meeting-decision-row" key={index}>
            <div className="meeting-decision-heading">
              <strong>决议事项 {index + 1}</strong>
              <button
                type="button"
                className="text-button danger"
                disabled={busy}
                onClick={() => remove(index)}
              >
                <Trash size={14} /> 删除
              </button>
            </div>
            <Field label="事项" full>
              <input
                value={row.title}
                disabled={busy}
                maxLength={300}
                placeholder="例如：审议支部委员会工作报告"
                onChange={(event) => update(index, "title", event.target.value)}
              />
            </Field>
            <Field label="结果">
              <select
                value={row.result}
                disabled={busy}
                onChange={(event) => update(index, "result", event.target.value)}
              >
                {RESULTS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            <div className="meeting-vote-grid">
              <Field label="同意">
                <input
                  type="number"
                  min="0"
                  value={row.agree_count}
                  disabled={busy}
                  onChange={(event) =>
                    update(index, "agree_count", event.target.value)
                  }
                />
              </Field>
              <Field label="反对">
                <input
                  type="number"
                  min="0"
                  value={row.oppose_count}
                  disabled={busy}
                  onChange={(event) =>
                    update(index, "oppose_count", event.target.value)
                  }
                />
              </Field>
              <Field label="弃权">
                <input
                  type="number"
                  min="0"
                  value={row.abstain_count}
                  disabled={busy}
                  onChange={(event) =>
                    update(index, "abstain_count", event.target.value)
                  }
                />
              </Field>
            </div>
            <Field label="说明" full>
              <textarea
                rows={2}
                value={row.note}
                disabled={busy}
                maxLength={2000}
                placeholder="可填写决议依据、不同意见或执行要求"
                onChange={(event) => update(index, "note", event.target.value)}
              />
            </Field>
          </div>
        ))}
      </div>
      <button
        type="button"
        className="button secondary"
        disabled={busy}
        onClick={add}
      >
        <Plus size={15} /> 增加决议事项
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
          <PencilSimple size={15} />
          {busy ? "正在保存…" : "保存决议与表决"}
        </button>
      </div>
    </Modal>
  );
}
