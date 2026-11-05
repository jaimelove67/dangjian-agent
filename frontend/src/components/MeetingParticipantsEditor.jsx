import { useEffect, useState } from "react";
import { CheckCircle, Plus, Trash, UsersThree } from "@phosphor-icons/react";
import { IS_LIVE, request } from "../api";
import { STAGE_LABELS } from "../contracts";
import {
  isAutoRosterType,
  mergeParticipantRows,
  participantStageLabel,
  participantSummary,
  rosterMembersForImport,
} from "../meeting-participants";

function demoStageCode(stage) {
  return (
    Object.keys(STAGE_LABELS).find((key) => STAGE_LABELS[key] === stage) ||
    stage ||
    ""
  );
}

export function MeetingParticipantsEditor({
  value = [],
  onChange,
  orgId = "",
  activityType = "branch_member_meeting",
  demoMembers = [],
  disabled = false,
}) {
  const [roster, setRoster] = useState([]);
  const [rosterLoading, setRosterLoading] = useState(false);
  const [rosterError, setRosterError] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const [rosterQuery, setRosterQuery] = useState("");
  const [notice, setNotice] = useState("");
  const [manualOpen, setManualOpen] = useState(false);
  const [manualName, setManualName] = useState("");
  const [manualId, setManualId] = useState("");
  const [manualError, setManualError] = useState("");

  useEffect(() => {
    setPickerOpen(false);
    setRoster([]);
    setSelectedIds([]);
    setRosterQuery("");
    setRosterError("");
    setNotice("");
    setManualOpen(false);
  }, [orgId, activityType]);

  async function loadRoster() {
    if (!orgId) throw new Error("请先选择会议所属组织。");
    if (!IS_LIVE) {
      return demoMembers
        .filter(
          (member) =>
            String(member.orgId || member.org_unit_id || "") === String(orgId),
        )
        .map((member) => ({
          participant_id: String(member.id || member.user_id || ""),
          name: member.name || "",
          org_name: member.organization || member.org_name || "",
          stage: demoStageCode(member.stage),
        }))
        .filter((member) => member.participant_id && member.name);
    }
    const members = [];
    let page = 1;
    let total = 0;
    do {
      const result = await request(
        `/member/roster?page=${page}&page_size=100&org_unit_id=${encodeURIComponent(orgId)}`,
      );
      members.push(...(result.items || []));
      total = Number(result.total || 0);
      page += 1;
    } while (members.length < total && page <= 5);
    return members.map((member) => ({
      participant_id: String(member.id || ""),
      name: member.name || "",
      org_name: member.org_name || "",
      stage: member.stage || "",
    }));
  }

  function openPicker(members = roster) {
    const existing = new Set(value.map((row) => String(row.participant_id)));
    setSelectedIds([]);
    setRosterQuery("");
    setRosterError("");
    setRoster(members);
    setPickerOpen(true);
    setNotice(
      members.some((member) => !existing.has(String(member.participant_id)))
        ? "勾选需要参加本次会议的人员，再点击“加入参会记录”。"
        : "名册人员已全部加入参会记录。",
    );
  }

  async function importFromRoster() {
    setRosterLoading(true);
    setRosterError("");
    setNotice("");
    try {
      const members = await loadRoster();
      setRoster(members);
      if (isAutoRosterType(activityType)) {
        const additions = rosterMembersForImport(members, activityType);
        if (!additions.length) {
          throw new Error("当前组织名册中没有符合本次会议范围的党员。");
        }
        const merged = mergeParticipantRows(value, additions);
        const added = merged.length - value.length;
        onChange(merged);
        setNotice(
          added > 0
            ? `已从支部名册带入 ${added} 人，请逐人确认出席或缺席。`
            : "名册人员已全部在参会记录中，请核对出勤。",
        );
        setPickerOpen(false);
      } else {
        openPicker(members);
        setNotice(
          "支委会、党小组会需人工选择参会人员；系统只提供名册，不自动判断支委或党小组成员。",
        );
      }
    } catch (failure) {
      setRosterError(failure.message || "读取支部名册失败，请稍后重试。");
    } finally {
      setRosterLoading(false);
    }
  }

  async function openOtherPicker() {
    if (roster.length) {
      openPicker(roster);
      return;
    }
    setRosterLoading(true);
    setRosterError("");
    try {
      const members = await loadRoster();
      setRoster(members);
      openPicker(members);
    } catch (failure) {
      setRosterError(failure.message || "读取支部名册失败，请稍后重试。");
    } finally {
      setRosterLoading(false);
    }
  }

  function toggleSelected(participantId) {
    setSelectedIds((previous) =>
      previous.includes(participantId)
        ? previous.filter((id) => id !== participantId)
        : [...previous, participantId],
    );
  }

  function addSelected() {
    const additions = roster.filter((member) =>
      selectedIds.includes(String(member.participant_id)),
    );
    if (!additions.length) return;
    const merged = mergeParticipantRows(value, additions);
    onChange(merged);
    setPickerOpen(false);
    setSelectedIds([]);
    setNotice(`已加入 ${merged.length - value.length} 人，请确认出勤。`);
  }

  function setAttendance(participantId, attended) {
    onChange(
      value.map((row) =>
        String(row.participant_id) === String(participantId)
          ? { ...row, attended }
          : row,
      ),
    );
  }

  function removeParticipant(participantId) {
    onChange(
      value.filter(
        (row) => String(row.participant_id) !== String(participantId),
      ),
    );
  }

  function addManualParticipant() {
    const name = manualName.trim();
    const participantId = manualId.trim();
    if (!name || !participantId) {
      setManualError("请填写姓名和人员编号。");
      return;
    }
    if (
      value.some(
        (row) => String(row.participant_id) === String(participantId),
      )
    ) {
      setManualError("该人员编号已在参会记录中。");
      return;
    }
    onChange([
      ...value,
      {
        participant_id: participantId,
        name,
        stage: "",
        org_name: "列席人员",
        attended: null,
        manual: true,
      },
    ]);
    setManualName("");
    setManualId("");
    setManualError("");
    setManualOpen(false);
    setNotice("已添加列席人员，请确认出勤。");
  }

  const summary = participantSummary(value);
  const existingIds = new Set(value.map((row) => String(row.participant_id)));
  const candidates = roster.filter(
    (member) =>
      !existingIds.has(String(member.participant_id)) &&
      (!rosterQuery.trim() ||
        member.name.includes(rosterQuery.trim()) ||
        participantStageLabel(member.stage).includes(rosterQuery.trim())),
  );
  const allVisibleSelected =
    candidates.length > 0 &&
    candidates.every((member) =>
      selectedIds.includes(String(member.participant_id)),
    );

  return (
    <div className="meeting-participant-editor">
      <div className="meeting-participant-head">
        <div>
          <strong>
            <UsersThree size={15} />
            实名参会记录
          </strong>
          <p>人员编号由系统按党员档案关联；名册外人员可手动添加。</p>
        </div>
        <div className="meeting-participant-actions">
          <button
            type="button"
            className="button secondary"
            disabled={disabled || rosterLoading}
            onClick={importFromRoster}
          >
            {rosterLoading
              ? "读取名册中…"
              : isAutoRosterType(activityType)
                ? "从支部名册带入"
                : "从名册选择"}
          </button>
          {isAutoRosterType(activityType) && value.length > 0 && (
            <button
              type="button"
              className="text-button"
              disabled={disabled || rosterLoading}
              onClick={openOtherPicker}
            >
              选择其他人员
            </button>
          )}
        </div>
      </div>
      {notice && <p className="meeting-participant-notice">{notice}</p>}
      {rosterError && (
        <p className="meeting-participant-error">{rosterError}</p>
      )}
      {value.length > 0 ? (
        <div className="meeting-participant-table-wrap">
          <table className="meeting-participant-table">
            <thead>
              <tr>
                <th>姓名</th>
                <th>身份 / 组织</th>
                <th>出勤</th>
                <th aria-label="操作" />
              </tr>
            </thead>
            <tbody>
              {value.map((row) => (
                <tr
                  key={row.participant_id}
                  className={
                    row.attended === true || row.attended === false
                      ? ""
                      : "pending"
                  }
                >
                  <td>
                    <strong>{row.name || "姓名待补"}</strong>
                    {row.manual && <small>列席</small>}
                  </td>
                  <td>
                    {row.stage
                      ? participantStageLabel(row.stage)
                      : row.org_name || "已登记人员"}
                  </td>
                  <td>
                    <span className="meeting-attendance-toggle">
                      <button
                        type="button"
                        aria-pressed={row.attended === true}
                        className={row.attended === true ? "active present" : ""}
                        disabled={disabled}
                        onClick={() =>
                          setAttendance(row.participant_id, true)
                        }
                      >
                        出席
                      </button>
                      <button
                        type="button"
                        aria-pressed={row.attended === false}
                        className={row.attended === false ? "active absent" : ""}
                        disabled={disabled}
                        onClick={() =>
                          setAttendance(row.participant_id, false)
                        }
                      >
                        缺席
                      </button>
                    </span>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="icon-button meeting-participant-remove"
                      aria-label={`移除${row.name || "参会人员"}`}
                      disabled={disabled}
                      onClick={() => removeParticipant(row.participant_id)}
                    >
                      <Trash size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="meeting-participant-empty">
          尚未登记参会人员。可从支部名册带入，或手动添加名册外人员。
        </p>
      )}
      <div className="meeting-participant-footer">
        <span>
          应到 <strong>{summary.total}</strong> 人
        </span>
        <span>
          实到 <strong>{summary.attended}</strong> 人
        </span>
        {summary.pending > 0 && (
          <span className="pending">
            待确认 <strong>{summary.pending}</strong> 人
          </span>
        )}
        <div className="meeting-participant-footer-actions">
          {value.length > 0 && (
            <>
              <button
                type="button"
                className="text-button"
                disabled={disabled}
                onClick={() =>
                  onChange(value.map((row) => ({ ...row, attended: true })))
                }
              >
                全部出席
              </button>
              <button
                type="button"
                className="text-button"
                disabled={disabled}
                onClick={() =>
                  onChange(value.map((row) => ({ ...row, attended: false })))
                }
              >
                全部缺席
              </button>
            </>
          )}
          <button
            type="button"
            className="text-button"
            disabled={disabled}
            onClick={() => setManualOpen((open) => !open)}
          >
            <Plus size={13} />
            手动添加
          </button>
        </div>
      </div>
      {manualOpen && (
        <div className="meeting-participant-manual">
          <input
            value={manualName}
            maxLength={100}
            placeholder="姓名"
            aria-label="列席人员姓名"
            onChange={(event) => {
              setManualName(event.target.value);
              setManualError("");
            }}
          />
          <input
            value={manualId}
            maxLength={100}
            placeholder="人员编号"
            aria-label="列席人员编号"
            onChange={(event) => {
              setManualId(event.target.value);
              setManualError("");
            }}
          />
          <button
            type="button"
            className="button secondary"
            disabled={disabled}
            onClick={addManualParticipant}
          >
            添加
          </button>
          {manualError && <p>{manualError}</p>}
        </div>
      )}
      {pickerOpen && (
        <div className="meeting-roster-picker">
          <div className="meeting-roster-picker-head">
            <div>
              <strong>从支部名册选择</strong>
              <span>只选择本次会议实际应参加的人员。</span>
            </div>
            <button
              type="button"
              className="text-button"
              onClick={() => setPickerOpen(false)}
            >
              收起
            </button>
          </div>
          <div className="meeting-roster-picker-tools">
            <input
              value={rosterQuery}
              placeholder="搜索姓名或身份"
              aria-label="搜索名册人员"
              onChange={(event) => setRosterQuery(event.target.value)}
            />
            <button
              type="button"
              className="text-button"
              disabled={!candidates.length}
              onClick={() =>
                setSelectedIds(
                  allVisibleSelected
                    ? []
                    : candidates.map((member) =>
                        String(member.participant_id),
                      ),
                )
              }
            >
              {allVisibleSelected ? "取消全选" : "全选"}
            </button>
          </div>
          <div className="meeting-roster-picker-list">
            {candidates.length > 0 ? (
              candidates.map((member) => {
                const participantId = String(member.participant_id);
                const checked = selectedIds.includes(participantId);
                return (
                  <label
                    key={participantId}
                    className={checked ? "selected" : ""}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleSelected(participantId)}
                    />
                    <span>
                      <strong>{member.name}</strong>
                      <small>
                        {participantStageLabel(member.stage)}
                        {member.org_name ? ` · ${member.org_name}` : ""}
                      </small>
                    </span>
                  </label>
                );
              })
            ) : (
              <p className="meeting-roster-picker-empty">
                没有可加入的名册人员。
              </p>
            )}
          </div>
          <div className="meeting-roster-picker-footer">
            <span>已选择 {selectedIds.length} 人</span>
            <button
              type="button"
              className="button primary"
              disabled={!selectedIds.length || disabled}
              onClick={addSelected}
            >
              <CheckCircle size={14} />
              加入参会记录
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
