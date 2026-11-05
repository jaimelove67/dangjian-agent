import { useEffect, useState } from "react";
import { backend } from "../api";
import { ErrorBox, Field, Loading, Modal } from "../components";

export function MeetingDocumentSettingsDialog({ onClose, onSaved }) {
  const [values, setValues] = useState({
    header: "",
    notice_footer: "",
    record_footer: "",
  });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    backend
      .meetingDocumentSettings()
      .then((data) => {
        if (active) setValues(data || {});
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
  }, []);

  function update(key, value) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const data = await backend.updateMeetingDocumentSettings(values);
      setValues(data);
      onSaved(data);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="学校会议文书设置"
      wide
      flat
      onClose={() => !busy && onClose()}
    >
      <p className="inline-note">
        这里的抬头和说明只影响之后新生成的会议文书；已经审核或归档的记录不会被自动改写。需要应用到历史草稿时，可使用“批量重建草稿文书”。
      </p>
      {error && <ErrorBox error={error} />}
      {loading ? (
        <Loading />
      ) : (
        <>
          <div className="form-grid">
            <Field label="会议文书抬头" full>
              <input
                value={values.header || ""}
                disabled={busy}
                maxLength={200}
                placeholder="例如：中共××学院总支部委员会"
                onChange={(event) => update("header", event.target.value)}
              />
            </Field>
            <Field label="会议通知补充要求" full>
              <textarea
                rows={3}
                value={values.notice_footer || ""}
                disabled={busy}
                maxLength={1000}
                placeholder="例如：请参会党员提前10分钟到场，因故不能参加须提前请假。"
                onChange={(event) => update("notice_footer", event.target.value)}
              />
            </Field>
            <Field label="会议记录补充说明" full>
              <textarea
                rows={3}
                value={values.record_footer || ""}
                disabled={busy}
                maxLength={1000}
                placeholder="例如：本记录由支部组织委员整理，经支部书记审核后归档。"
                onChange={(event) => update("record_footer", event.target.value)}
              />
            </Field>
          </div>
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
              {busy ? "正在保存…" : "保存文书设置"}
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}
