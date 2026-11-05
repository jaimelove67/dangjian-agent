import { useEffect, useState } from "react";
import { backend } from "../api";
import { ErrorBox, Field, Loading, Modal } from "../components";

export function MeetingDocumentSettingsDialog({ orgs = [], onClose, onSaved }) {
  const [values, setValues] = useState({
    header: "",
    notice_footer: "",
    record_footer: "",
  });
  const [scopeOrgId, setScopeOrgId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function load(scope = scopeOrgId) {
    setLoading(true);
    setError(null);
    try {
      const data = await backend.meetingDocumentSettings(scope);
      setValues(data || {});
    } catch (failure) {
      setError(failure);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load("");
  }, []);

  function update(key, value) {
    setValues((current) => ({ ...current, [key]: value }));
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const data = await backend.updateMeetingDocumentSettings({
        ...values,
        org_unit_id: scopeOrgId || undefined,
      });
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
        这里可以维护学校默认或院系、支部覆盖的抬头和说明；未单独设置的组织继承上级。设置只影响之后新生成的会议文书，已经审核或归档的记录不会被自动改写；历史草稿可使用“批量重建草稿文书”。
      </p>
      {error && <ErrorBox error={error} />}
      {loading ? (
        <Loading />
      ) : (
        <>
          <div className="form-grid">
            <Field label="适用范围" full>
              <select
                value={scopeOrgId}
                disabled={busy}
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
