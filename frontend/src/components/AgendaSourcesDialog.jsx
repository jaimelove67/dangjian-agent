import { useEffect, useState } from "react";
import { CheckCircle, FileText } from "@phosphor-icons/react";
import { backend } from "../api";
import { roleApi } from "../role-api";
import { Badge, Empty, ErrorBox, Field, Loading, Modal } from "../components";

function dateOnly(value) {
  return value ? String(value).slice(0, 10) : "日期未识别";
}

const STATUS = {
  pending: { label: "待审核，采用后写入知识库", tone: "orange" },
  approved: { label: "已采用", tone: "green" },
};

export function AgendaSourcesDialog({ record, onClose, onGenerated }) {
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState([]);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    backend
      .externalSuggestions(record.id)
      .then((result) => {
        if (!active) return;
        const next = result.items || [];
        setItems(next);
        setSelected(next.slice(0, 3).map((item) => item.id));
      })
      .catch((failure) => {
        if (active) setError(failure);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [record.id]);

  function toggle(id) {
    setSelected((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : current.length >= 5
          ? current
          : [...current, id],
    );
  }

  async function generate(useSources = true) {
    setBusy(true);
    setError(null);
    try {
      const reason =
        note.trim() ||
        (useSources
          ? "根据已审核的最新资料生成会议议程草稿"
          : "不使用最新资料，按当前会议信息生成议程草稿");
      const next = useSources
        ? await backend.generateAgendaFromUpdates(record.id, {
            expected_revision: record.revision,
            reason,
            external_update_ids: selected,
          })
        : await roleApi.meetingAction(
            record.id,
            "generate-agenda",
            record.revision,
            reason,
          );
      onGenerated(next);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="用最新资料生成议程"
      wide
      flat
      onClose={() => !busy && onClose()}
    >
      <p className="inline-note">
        勾选本次会议需要学习的最新资料，系统会一次性采用所选资料并生成议程草稿。生成内容仅作会前准备，不替代真实会议记录；参会人员、表决结果和会议决议仍由组织人工办理。
      </p>
      {error && <ErrorBox error={error} />}
      {loading ? (
        <Loading />
      ) : (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>选择</th>
                  <th>资料 / 来源</th>
                  <th>发布日期</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const status = STATUS[item.status] || {
                    label: item.status,
                    tone: "gray",
                  };
                  return (
                    <tr key={item.id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selected.includes(item.id)}
                          onChange={() => toggle(item.id)}
                          disabled={busy}
                          aria-label={`选择${item.title}`}
                        />
                      </td>
                      <td>
                        <a
                          href={item.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-button link"
                        >
                          <FileText size={15} /> {item.title}
                        </a>
                        <small className="cell-subtext">
                          {item.source_name} · {dateOnly(item.published_at)}
                        </small>
                        {item.summary && (
                          <small className="cell-subtext">
                            {item.summary.slice(0, 180)}
                            {item.summary.length > 180 ? "…" : ""}
                          </small>
                        )}
                      </td>
                      <td>{dateOnly(item.published_at)}</td>
                      <td>
                        <Badge tone={status.tone}>{status.label}</Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {!items.length && (
              <Empty
                title="暂无可用的最新资料"
                description="可以先不使用最新资料生成议程，或由院系/学校管理员先在“最新资料”中抓取并审核。"
              />
            )}
          </div>
          <Field label="生成说明（可选）" full>
            <input
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={2000}
              placeholder="例如：本月党课围绕全面从严治党最新部署开展学习"
            />
          </Field>
        </>
      )}
      <div className="modal-actions">
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={() => generate(false)}
        >
          不使用最新资料直接生成
        </button>
        <button
          type="button"
          className="button primary"
          disabled={busy || loading || !selected.length}
          onClick={() => generate(true)}
        >
          <CheckCircle size={16} />
          {busy ? "正在生成…" : `采用所选 ${selected.length} 条并生成议程`}
        </button>
      </div>
    </Modal>
  );
}
