import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  CheckCircle,
  Clock,
  IdentificationCard,
  PencilSimple,
  Printer,
  WarningCircle,
} from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE } from "../api";
import { roleApi } from "../role-api";
import {
  Badge,
  Empty,
  ErrorBox,
  Field,
  Loading,
  Modal,
  PageHeader,
  PanelTitle,
  SearchInput,
  Select,
  Tabs,
  downloadBlob,
} from "../components";
import {
  INFO_STATUS,
  INFO_STATUS_ORDER,
  canEditBranchInfo,
  canReviewInfo,
  emptyInfoPayload,
  infoCollectionById,
  infoCounts,
  infoProfile,
  infoProfileFromCollection,
  infoStatusLabel,
  infoStatusTone,
  isEligibleProfile,
  mergeBranchPayload,
  normalizeInfoPayload,
  personCategory,
  reviewActionLabel,
  reviewInfoCollection,
  saveBranchInfo,
  saveSelfInfo,
  scopedInfoCollections,
  selfInfoCollection,
  submitSelfInfo,
  validateSelfInfo,
  infoStatusLabel as statusLabel,
} from "../member-info";

function formatTime(value) {
  if (!value) return "—";
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) {
    // 后端时间字段为 UTC 无时区字符串；没有偏移量时按 UTC 解析，避免少 8 小时。
    const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(text) ? text : `${text}Z`;
    const date = new Date(normalized);
    if (!Number.isNaN(date.getTime()))
      return new Intl.DateTimeFormat("zh-CN", {
        timeZone: "Asia/Shanghai",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
  }
  return text.replace("T", " ").slice(0, 16);
}

function display(value, fallback = "未填写") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

function genderLabel(value) {
  return { male: "男", female: "女" }[value] || "未填写";
}

function partyStatusLabel(value) {
  return { normal: "正常", suspended: "停止党籍" }[value] || "未填写";
}

function filingTypeLabel(value) {
  return { new: "当年新发展党员", supplement: "往年党员补录" }[value] || "未填写";
}

function infoValue(key, payload) {
  const value = payload?.[key];
  if (key === "gender") return genderLabel(value);
  if (key === "party_status") return partyStatusLabel(value);
  if (key === "filing_type") return filingTypeLabel(value);
  if (key === "lost_contact" || key === "floating" || key === "relation_transfer")
    return display(value, "未填写");
  return display(value);
}

function errorFor(errors, key) {
  return errors?.[key] ? <small className="field-error">{errors[key]}</small> : null;
}

function FieldError({ errors, name }) {
  return errorFor(errors, name);
}

function InfoSummary({ payload, profile, compact = false, branchFilled = true }) {
  const values = normalizeInfoPayload(payload);
  const branch = (value) => (branchFilled ? value : "待支部补录");
  const items = [
    ["姓名", profile?.name],
    ["人员类别", personCategory(profile?.stage)],
    ["性别", genderLabel(values.gender)],
    ["民族", values.ethnicity],
    ["学历代码", values.education_code],
    ["手机号", values.mobile],
    ["固定电话", [values.phone_area, values.phone_number].filter(Boolean).join("-")],
    ["家庭住址", values.address],
    ["是否失联", values.lost_contact ? "是" : "否"],
    ["是否流动", values.floating ? "是" : "否"],
    ["加入党组织日期", branch(values.join_party_on)],
    ["转为正式党员日期", branch(values.full_member_on)],
    ["工作岗位代码", branch(values.job_code)],
    ["党籍状态", branch(partyStatusLabel(values.party_status))],
    ["填报类型", branch(filingTypeLabel(values.filing_type))],
    [
      "是否转接组织关系",
      branch(
        values.relation_transfer === true
          ? "是"
          : values.relation_transfer === false
            ? "否"
            : "",
      ),
    ],
  ];
  return (
    <dl className={`member-info-summary ${compact ? "compact" : ""}`}>
      {items.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{display(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

const INFO_ACTION_LABELS = {
  create: "登记采集表",
  submit: "本人确认提交",
  branch_save: "支部补录核对",
  branch_approve: "支部初核通过",
  department_approve: "院系复核通过",
  archive: "学校备案归档",
  return: "退回补正",
};

function InfoTimeline({ collection }) {
  const history = collection?.history || [];
  const fallback = collection?.created_at
    ? [
        {
          action: "create",
          actor: collection.member_name,
          status: collection.status,
          at: collection.created_at,
          opinion: "登记基本信息采集表",
        },
      ]
    : [];
  const events = history.length ? history : fallback;
  if (!events.length) return null;
  return (
    <ol className="member-info-timeline">
      {events.map((event, index) => (
        <li key={`${event.at}-${index}`}>
          <span className="timeline-dot">
            {event.status === "archived" ? (
              <CheckCircle size={15} weight="fill" />
            ) : (
              <Clock size={15} />
            )}
          </span>
          <div>
            <strong>
              {INFO_ACTION_LABELS[event.action] ||
                statusLabel(event.status) ||
                event.action}
            </strong>
            <p>
              {event.actor || "系统"} · {formatTime(event.at)}
              {event.version ? ` · 第 ${event.version} 版` : ""}
            </p>
            {event.opinion && <small>{event.opinion}</small>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function AutoFields({ profile }) {
  const info = infoProfile(profile);
  if (!info) return null;
  return (
    <div className="member-info-auto">
      <div>
        <span>姓名</span>
        <strong>{info.name}</strong>
      </div>
      <div>
        <span>身份证号</span>
        <strong>{info.id_card_masked || "档案未登记"}</strong>
      </div>
      <div>
        <span>出生日期</span>
        <strong>{info.birth_date || "档案未登记"}</strong>
      </div>
      <div>
        <span>所在党支部</span>
        <strong>{info.org_name}</strong>
      </div>
      <div>
        <span>人员类别</span>
        <strong>{info.person_category}</strong>
      </div>
    </div>
  );
}

function MemberInfoForm({
  mode = "self",
  profile,
  collection,
  initial,
  onSave,
  onSubmit,
  onClose,
}) {
  const [payload, setPayload] = useState(() =>
    normalizeInfoPayload(initial || collection?.payload || emptyInfoPayload()),
  );
  const [confirmed, setConfirmed] = useState(false);
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState(null);
  const branchMode = mode === "branch";
  const info = profile ? infoProfile(profile) : infoProfileFromCollection(collection || {});
  const stage = info?.stage || collection?.member_stage || "";

  function set(key, value) {
    setPayload((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => ({ ...prev, [key]: undefined }));
  }

  async function saveDraft() {
    setFormError(null);
    setErrors({});
    setBusy(true);
    try {
      // 草稿允许不完整；提交或审核通过时才做完整校验。
      await onSave(payload);
      onClose();
    } catch (error) {
      setFormError(error.message || "保存失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    setFormError(null);
    const check = validateSelfInfo(payload);
    if (Object.keys(check).length) {
      setErrors(check);
      setFormError("请先完善标记的必填项，再提交。");
      return;
    }
    if (!confirmed) {
      setFormError("请先勾选“本人已核对以上信息，确认无误”。");
      return;
    }
    setBusy(true);
    try {
      await onSubmit(payload, true);
      onClose();
    } catch (error) {
      setFormError(error.message || "提交失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="member-info-form">
      <AutoFields profile={profile || { ...collection, stage: collection?.member_stage }} />
      <div className="member-info-form-note">
        姓名、身份证号、出生日期、所在党支部和人员类别以组织档案为准，本人不能直接修改。
      </div>

      <PanelTitle title={branchMode ? "本人填写信息" : "本人填写"} />
      <div className="member-info-form-grid">
        <Field label="性别" required>
          <Select
            label="性别"
            value={payload.gender}
            onChange={(event) => set("gender", event.target.value)}
          >
            <option value="">请选择</option>
            <option value="male">男</option>
            <option value="female">女</option>
          </Select>
          <FieldError errors={errors} name="gender" />
        </Field>
        <Field label="民族" required>
          <input
            value={payload.ethnicity}
            maxLength={30}
            placeholder="如：汉族"
            onChange={(event) => set("ethnicity", event.target.value)}
          />
          <FieldError errors={errors} name="ethnicity" />
        </Field>
        <Field label="学历代码" required>
          <input
            value={payload.education_code}
            maxLength={10}
            placeholder="按学校《学历代码》填写，如 22"
            onChange={(event) => set("education_code", event.target.value)}
          />
          <FieldError errors={errors} name="education_code" />
        </Field>
        <Field label="手机号" required>
          <input
            value={payload.mobile}
            maxLength={11}
            inputMode="tel"
            placeholder="11 位手机号"
            onChange={(event) => set("mobile", event.target.value)}
          />
          <FieldError errors={errors} name="mobile" />
        </Field>
        <Field label="固定电话（选填）">
          <div className="member-info-phone">
            <input
              value={payload.phone_area}
              maxLength={4}
              inputMode="numeric"
              placeholder="区号"
              onChange={(event) => set("phone_area", event.target.value)}
            />
            <span>—</span>
            <input
              value={payload.phone_number}
              maxLength={8}
              inputMode="numeric"
              placeholder="电话号码"
              onChange={(event) => set("phone_number", event.target.value)}
            />
          </div>
          <FieldError errors={errors} name="phone_area" />
          <FieldError errors={errors} name="phone_number" />
        </Field>
        <Field label="家庭住址" required full>
          <textarea
            value={payload.address}
            maxLength={200}
            rows={2}
            placeholder="具体到门牌号"
            onChange={(event) => set("address", event.target.value)}
          />
          <FieldError errors={errors} name="address" />
        </Field>
        <Field label="是否失联党员" required>
          <Select
            label="是否失联党员"
            value={payload.lost_contact ? "yes" : "no"}
            onChange={(event) => set("lost_contact", event.target.value === "yes")}
          >
            <option value="no">否</option>
            <option value="yes">是</option>
          </Select>
          <FieldError errors={errors} name="lost_contact" />
        </Field>
        {payload.lost_contact && (
          <Field label="失去联系日期" required>
            <input
              type="date"
              value={payload.lost_contact_on}
              onChange={(event) => set("lost_contact_on", event.target.value)}
            />
            <FieldError errors={errors} name="lost_contact_on" />
          </Field>
        )}
        <Field label="是否流动党员" required>
          <Select
            label="是否流动党员"
            value={payload.floating ? "yes" : "no"}
            onChange={(event) => set("floating", event.target.value === "yes")}
          >
            <option value="no">否</option>
            <option value="yes">是</option>
          </Select>
          <FieldError errors={errors} name="floating" />
        </Field>
        {payload.floating && (
          <>
            <Field label="外出流向省份" required>
              <input
                value={payload.floating_province}
                maxLength={50}
                placeholder="省（区、市）"
                onChange={(event) => set("floating_province", event.target.value)}
              />
              <FieldError errors={errors} name="floating_province" />
            </Field>
            <Field label="外出流向城市" required>
              <input
                value={payload.floating_city}
                maxLength={50}
                placeholder="市（地、州、盟）"
                onChange={(event) => set("floating_city", event.target.value)}
              />
              <FieldError errors={errors} name="floating_city" />
            </Field>
            <Field label="外出流向县区" required>
              <input
                value={payload.floating_county}
                maxLength={50}
                placeholder="县（市、区、旗）"
                onChange={(event) => set("floating_county", event.target.value)}
              />
              <FieldError errors={errors} name="floating_county" />
            </Field>
          </>
        )}
      </div>

      <PanelTitle
        title={branchMode ? "支部补录与核对" : "以下由支部补录"}
        action={branchMode ? null : "无需本人填写"}
      />
      {branchMode ? (
        <div className="member-info-form-grid">
          <Field label="加入党组织日期" required>
            <input
              type="date"
              value={payload.join_party_on}
              onChange={(event) => set("join_party_on", event.target.value)}
            />
            <FieldError errors={errors} name="join_party_on" />
          </Field>
          <Field label="转为正式党员日期" required={stage === "member"}>
            <input
              type="date"
              value={payload.full_member_on}
              onChange={(event) => set("full_member_on", event.target.value)}
            />
            <FieldError errors={errors} name="full_member_on" />
          </Field>
          <Field label="工作岗位代码" required>
            <input
              value={payload.job_code}
              maxLength={10}
              placeholder="按学校《工作岗位代码》填写"
              onChange={(event) => set("job_code", event.target.value)}
            />
            <FieldError errors={errors} name="job_code" />
          </Field>
          <Field label="党籍状态" required>
            <Select
              label="党籍状态"
              value={payload.party_status}
              onChange={(event) => set("party_status", event.target.value)}
            >
              <option value="">请选择</option>
              <option value="normal">正常</option>
              <option value="suspended">停止党籍</option>
            </Select>
            <FieldError errors={errors} name="party_status" />
          </Field>
          <Field label="填报类型" required>
            <Select
              label="填报类型"
              value={payload.filing_type}
              onChange={(event) => set("filing_type", event.target.value)}
            >
              <option value="">请选择</option>
              <option value="new">当年新发展党员</option>
              <option value="supplement">往年党员补录</option>
            </Select>
            <FieldError errors={errors} name="filing_type" />
          </Field>
          {payload.filing_type === "supplement" && (
            <Field label="补录原因" required full>
              <textarea
                value={payload.supplement_reason}
                maxLength={500}
                rows={2}
                onChange={(event) => set("supplement_reason", event.target.value)}
              />
              <FieldError errors={errors} name="supplement_reason" />
            </Field>
          )}
          <Field label="是否转接组织关系" required>
            <Select
              label="是否转接组织关系"
              value={
                payload.relation_transfer === true
                  ? "yes"
                  : payload.relation_transfer === false
                    ? "no"
                    : ""
              }
              onChange={(event) =>
                set(
                  "relation_transfer",
                  event.target.value === "" ? null : event.target.value === "yes",
                )
              }
            >
              <option value="">请选择</option>
              <option value="no">否</option>
              <option value="yes">是</option>
            </Select>
            <FieldError errors={errors} name="relation_transfer" />
          </Field>
          {payload.relation_transfer && (
            <Field label="转入组织关系支部全称" required full>
              <input
                value={payload.transfer_branch}
                maxLength={200}
                onChange={(event) => set("transfer_branch", event.target.value)}
              />
              <FieldError errors={errors} name="transfer_branch" />
            </Field>
          )}
        </div>
      ) : (
        <dl className="member-info-branch-summary">
          {[
            "加入党组织日期",
            "转为正式党员日期",
            "工作岗位代码",
            "党籍状态",
            "填报类型",
            "是否转接组织关系",
          ].map((label) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>待支部补录</dd>
            </div>
          ))}
        </dl>
      )}

      {formError && (
        <div className="info-form-error" role="alert">
          <WarningCircle size={18} />
          {formError}
        </div>
      )}
      {!branchMode && (
        <label className="member-info-confirm">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          本人已核对以上信息，确认无误。
        </label>
      )}
      <div className="modal-actions">
        <button type="button" className="button secondary" onClick={onClose} disabled={busy}>
          取消
        </button>
        <button type="button" className="button secondary" onClick={saveDraft} disabled={busy}>
          {busy ? "正在保存…" : branchMode ? "保存补录信息" : "保存草稿"}
        </button>
        {!branchMode && (
          <button type="button" className="button primary" onClick={submit} disabled={busy}>
            {busy ? "正在提交…" : "确认提交"}
          </button>
        )}
      </div>
    </div>
  );
}

function InfoPrint({ collection, onClose }) {
  const profile = infoProfileFromCollection(collection);
  const payload = normalizeInfoPayload(collection.payload);
  const branchFilled = ["branch_approved", "department_approved", "archived"].includes(
    collection.status,
  );
  const branch = (value) => (branchFilled ? display(value) : "待支部补录");
  const rows = [
    ["1. 姓名", profile.name],
    ["2. 性别", genderLabel(payload.gender)],
    ["3. 民族", display(payload.ethnicity)],
    ["4. 公民身份证号", profile.id_card_masked || "档案未登记"],
    ["5. 出生日期", display(profile.birth_date)],
    ["6. 学历代码", display(payload.education_code)],
    ["7. 人员类别", profile.person_category],
    ["8. 所在党支部", profile.org_name],
    ["9. 加入党组织日期", branch(payload.join_party_on)],
    ["10. 转为正式党员日期", branch(payload.full_member_on)],
    ["11. 工作岗位代码", branch(payload.job_code)],
    ["12. 联系电话", [payload.mobile, payload.phone_area && payload.phone_number ? `${payload.phone_area}-${payload.phone_number}` : ""].filter(Boolean).join(" / ")],
    ["13. 家庭住址", display(payload.address)],
    ["14. 党籍状态", branch(partyStatusLabel(payload.party_status))],
    ["15. 是否失联党员", payload.lost_contact ? `是，失去联系日期：${display(payload.lost_contact_on)}` : "否"],
    ["16. 是否流动党员", payload.floating ? `是，流向：${[payload.floating_province, payload.floating_city, payload.floating_county].filter(Boolean).join(" ")}` : "否"],
    ["17. 填报类型", branch(filingTypeLabel(payload.filing_type))],
    [
      "18. 是否转接组织关系",
      branch(
        payload.relation_transfer === true
          ? `是，转入支部：${display(payload.transfer_branch)}`
          : payload.relation_transfer === false
            ? "否"
            : "",
      ),
    ],
  ];
  function print() {
    const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>党员基本信息采集表</title><style>
      @page { size: A4; margin: 18mm 16mm; }
      body { font-family: "SimSun", "Songti SC", serif; color: #111; font-size: 13px; line-height: 1.7; }
      h1 { text-align: center; font-size: 22px; letter-spacing: 4px; margin: 0 0 6px; }
      .meta { text-align: right; color: #555; margin-bottom: 18px; }
      .row { display: flex; gap: 10px; border-bottom: 1px solid #ddd; padding: 5px 0; }
      .row b { min-width: 150px; font-weight: 600; }
      .row span { flex: 1; }
      .sign { margin-top: 28px; display: grid; grid-template-columns: 1fr 1fr; gap: 30px 50px; }
      .sign div { min-height: 44px; border-bottom: 1px solid #333; }
      .note { margin-top: 22px; font-size: 12px; color: #444; }
      .watermark { color: #888; font-size: 11px; margin-top: 8px; }
    </style></head><body>
      <div class="meta">附件 2</div>
      <h1>党员基本信息采集表</h1>
      ${rows.map(([label, value]) => `<div class="row"><b>${label}：</b><span>${escapeHtml(value)}</span></div>`).join("")}
      <div class="sign">
        <div>党员（签字）：${escapeHtml(collection.member_confirmed_at ? `已在线确认 ${formatTime(collection.member_confirmed_at)}` : "")}</div>
        <div>信息采集员（签字）：${escapeHtml(collection.collector_name || "")}</div>
        <div>党支部书记（签字）：${escapeHtml(collection.branch_reviewed_by_name || "")}</div>
        <div>党总支复核（党总支公章）：${escapeHtml(collection.department_reviewed_by_name || "")}</div>
      </div>
      <div class="note">注：本表一式两份，由党员本人填写并确认，经党支部初核、党总支复核后，一份交学校党校备案，一份由党支部留存。</div>
      <div class="watermark">系统打印件；身份证号按页面脱敏值显示，完整号码请按身份证原件核对填写。</div>
    </body></html>`;
    const win = window.open("", "_blank", "noopener,noreferrer");
    if (!win) throw new Error("浏览器拦截了打印窗口，请允许弹出窗口后重试。");
    win.document.write(html);
    win.document.close();
    win.focus();
    setTimeout(() => win.print(), 300);
  }
  return (
    <Modal title="打印党员基本信息采集表" wide flat onClose={onClose}>
      <div className="member-info-print-preview">
        <h3>党员基本信息采集表</h3>
        {rows.map(([label, value]) => (
          <p key={label}>
            <strong>{label}：</strong>
            {display(value)}
          </p>
        ))}
        <div className="inline-note">
          页面只展示脱敏身份证号。打印件请按身份证原件核对完整号码后使用。
        </div>
      </div>
      <div className="modal-actions">
        <button className="button secondary" onClick={onClose}>
          关闭
        </button>
        <button className="button primary" onClick={print}>
          <Printer size={17} />
          打印 / 另存为 PDF
        </button>
      </div>
    </Modal>
  );
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function MemberInfoSelfSection({ profile }) {
  const { session } = useApp();
  const { data, update, notify } = useStore();
  const [live, setLive] = useState(null);
  const [loading, setLoading] = useState(IS_LIVE);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  const [editing, setEditing] = useState(false);
  const [printing, setPrinting] = useState(false);

  useEffect(() => {
    if (!IS_LIVE || !profile) return;
    let active = true;
    setLoading(true);
    setError(null);
    roleApi
      .selfInfo()
      .then((result) => {
        if (active) setLive(result);
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
  }, [profile?.id, tick]);

  const demoCollection = !IS_LIVE ? selfInfoCollection(data, session) : null;
  const collection = IS_LIVE ? live?.collection || null : demoCollection;
  const eligible = isEligibleProfile(profile);
  const canEdit =
    eligible && (!collection || ["draft", "returned"].includes(collection.status));
  const initial = collection?.payload || {
    ...emptyInfoPayload(),
    gender: profile?.gender === "男" ? "male" : profile?.gender === "女" ? "female" : "",
  };

  async function save(payload) {
    if (IS_LIVE) {
      await roleApi.saveSelfInfo(payload);
      setTick((value) => value + 1);
    } else {
      const result = saveSelfInfo(data, session, payload);
      update("memberInfoCollections", result.collections);
    }
    notify("基本信息已保存为草稿");
  }

  async function submit(payload, confirmed) {
    if (IS_LIVE) {
      await roleApi.submitSelfInfo({ ...payload, confirmed });
      setTick((value) => value + 1);
    } else {
      const result = submitSelfInfo(data, session, payload, confirmed);
      update("memberInfoCollections", result.collections);
    }
    notify("基本信息已提交，等待支部初核");
  }

  if (!profile) return null;
  if (!eligible) {
    return (
      <section className="member-info-card">
        <div className="member-info-card-head">
          <div>
            <h3>基本信息采集</h3>
            <p>党员基本信息采集表在成为预备党员后开放填写。</p>
          </div>
          <Badge tone="gray">暂未开放</Badge>
        </div>
        <div className="inline-note">
          当前登记阶段为“{profile.stage}”。发展为预备党员后，由组织通知填写。
        </div>
      </section>
    );
  }
  if (loading) return <Loading />;
  if (error) return <ErrorBox error={error} retry={() => setTick((value) => value + 1)} />;

  return (
    <>
      <section className="member-info-card">
        <div className="member-info-card-head">
          <div>
            <h3>基本信息采集</h3>
            <p>本人填写个人信息，支部补录组织信息，逐级审核后备案。</p>
          </div>
          <Badge tone={infoStatusTone(collection?.status || "draft")}>
            {collection ? infoStatusLabel(collection.status) : "待填写"}
          </Badge>
        </div>
        {collection ? (
          <>
            <InfoSummary
              payload={collection.payload}
              profile={profile}
              compact
              branchFilled={["branch_approved", "department_approved", "archived"].includes(
                collection.status,
              )}
            />
            {collection.status === "returned" && collection.return_reason && (
              <div className="member-info-return">
                <WarningCircle size={18} />
                <div>
                  <strong>退回原因</strong>
                  <p>{collection.return_reason}</p>
                  <small>
                    {collection.returned_by_name || "组织人员"} · {formatTime(collection.returned_at)}
                  </small>
                </div>
              </div>
            )}
            <InfoTimeline collection={collection} />
          </>
        ) : (
          <div className="member-info-empty">
            <IdentificationCard size={32} weight="duotone" />
            <div>
              <strong>尚未填写基本信息采集表</strong>
              <p>请先核对档案中的姓名、身份证号、出生日期和所在支部，再填写本人信息。</p>
            </div>
          </div>
        )}
        <div className="member-info-actions">
          {canEdit && (
            <button className="button primary" onClick={() => setEditing(true)}>
              <PencilSimple size={17} />
              {collection ? (collection.status === "returned" ? "修改后重新提交" : "继续填写") : "开始填写"}
            </button>
          )}
          {collection && (
            <button className="button secondary" onClick={() => setPrinting(true)}>
              <Printer size={17} />
              打印采集表
            </button>
          )}
          {collection && !canEdit && collection.status !== "archived" && (
            <span className="inline-note">当前处于审核环节，暂不能修改。</span>
          )}
          {collection?.status === "archived" && (
            <span className="inline-note">已备案。信息需要变更时，请联系支部发起新的采集版本。</span>
          )}
        </div>
      </section>
      {editing && (
        <Modal
          title={collection ? "填写党员基本信息采集表" : "开始填写党员基本信息采集表"}
          wide
          flat
          onClose={() => setEditing(false)}
        >
          <MemberInfoForm
            key={`${collection?.id || "new"}-${collection?.status || "draft"}`}
            profile={profile}
            collection={collection}
            initial={initial}
            onSave={save}
            onSubmit={submit}
            onClose={() => setEditing(false)}
          />
        </Modal>
      )}
      {printing && collection && (
        <InfoPrint collection={collection} onClose={() => setPrinting(false)} />
      )}
    </>
  );
}

export function MemberInfoPage() {
  const { session } = useApp();
  const { data, update, notify } = useStore();
  const [live, setLive] = useState({ items: [], counts: {} });
  const [loading, setLoading] = useState(IS_LIVE);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);
  const [tab, setTab] = useState("all");
  const [query, setQuery] = useState("");
  const [org, setOrg] = useState("");
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);
  const [editing, setEditing] = useState(false);
  const [review, setReview] = useState(null);
  const [reviewOpinion, setReviewOpinion] = useState("");
  const [reviewError, setReviewError] = useState(null);
  const [reviewBusy, setReviewBusy] = useState(false);

  useEffect(() => {
    if (!IS_LIVE) return;
    let active = true;
    setLoading(true);
    setError(null);
    roleApi
      .infoCollections()
      .then((result) => {
        if (active) setLive(result || { items: [], counts: {} });
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
  }, [tick]);

  const demoItems = !IS_LIVE ? scopedInfoCollections(data, session) : [];
  const allItems = IS_LIVE ? live.items || [] : demoItems;
  const counts = IS_LIVE ? live.counts || infoCounts(allItems) : infoCounts(allItems);
  const orgOptions = useMemo(() => {
    const values = new Set(allItems.map((item) => item.org_name).filter(Boolean));
    return [...values].sort((a, b) => a.localeCompare(b, "zh-CN"));
  }, [allItems]);
  const filtered = useMemo(
    () =>
      allItems.filter(
        (item) =>
          (tab === "all" || item.status === tab) &&
          (!org || item.org_name === org) &&
          (!query ||
            `${item.member_name} ${item.org_name} ${item.member_stage_label || ""}`
              .toLowerCase()
              .includes(query.toLowerCase())),
      ),
    [allItems, tab, org, query],
  );
  const tabs = [
    { id: "all", label: `全部 ${allItems.length}` },
    ...INFO_STATUS_ORDER.filter((status) =>
      ["submitted", "branch_approved", "department_approved", "returned", "archived"].includes(status),
    ).map((status) => ({
      id: status,
      label: `${INFO_STATUS[status].label} ${counts[status] || 0}`,
    })),
  ];

  async function openDetail(item) {
    setSelected(item.id);
    setDetail(item);
    setDetailError(null);
    if (!IS_LIVE) return;
    setDetailLoading(true);
    try {
      setDetail(await roleApi.infoCollection(item.id));
    } catch (failure) {
      setDetailError(failure);
    } finally {
      setDetailLoading(false);
    }
  }

  function closeDetail() {
    setSelected(null);
    setDetail(null);
    setDetailError(null);
    setEditing(false);
    setReview(null);
  }

  function refresh() {
    setTick((value) => value + 1);
    if (!IS_LIVE && selected) {
      const current = infoCollectionById(data, selected);
      if (current) setDetail(current);
    }
  }

  async function saveBranch(payload) {
    if (IS_LIVE) {
      await roleApi.saveInfoCollection(detail.id, payload);
      setTick((value) => value + 1);
      setDetail(await roleApi.infoCollection(detail.id));
    } else {
      const collections = saveBranchInfo(data, session, detail.id, payload);
      update("memberInfoCollections", collections);
      setDetail(infoCollectionById({ memberInfoCollections: collections }, detail.id));
    }
    notify("支部补录信息已保存");
  }

  async function submitReview() {
    if (!review) return;
    const text = reviewOpinion.trim();
    if (!text) {
      setReviewError("请填写处理意见。");
      return;
    }
    setReviewBusy(true);
    setReviewError(null);
    try {
      if (IS_LIVE) {
        await roleApi.reviewInfoCollection(detail.id, {
          decision: review.action,
          opinion: text,
        });
        setTick((value) => value + 1);
      } else {
        const collections = reviewInfoCollection(
          data,
          session,
          detail.id,
          review.action,
          text,
        );
        update("memberInfoCollections", collections);
      }
      notify(
        review.action === "return"
          ? "采集表已退回本人补正"
          : review.action === "archive"
            ? "采集表已备案归档"
            : "审核已通过",
      );
      setReview(null);
      setReviewOpinion("");
      closeDetail();
    } catch (failure) {
      setReviewError(failure.message || "处理失败，请稍后重试。");
    } finally {
      setReviewBusy(false);
    }
  }

  async function exportWord() {
    if (!detail || !IS_LIVE) return;
    try {
      const blob = await roleApi.exportInfoCollection(detail.id);
      downloadBlob(
        blob,
        `党员基本信息采集表-${detail.member_name}-第${detail.version}版.docx`,
      );
      notify("采集表已导出");
    } catch (failure) {
      notify(failure.message || "导出失败，请稍后重试。");
    }
  }

  const canReview = detail
    ? canReviewInfo(session, detail, !IS_LIVE)
    : false;
  const canEdit = detail
    ? canEditBranchInfo(session, detail, !IS_LIVE)
    : false;
  const actionLabel = detail ? reviewActionLabel(session, detail) : "";
  const profile = detail ? infoProfileFromCollection(detail) : null;

  return (
    <section className="panel workspace-panel">
      <PageHeader
        title="党员信息采集"
        subtitle="本人填写、支部初核、院系复核、学校备案"
        action={
          <button className="button secondary" onClick={refresh}>
            刷新
          </button>
        }
      />
      <Tabs items={tabs} active={tab} onChange={setTab} />
      <div className="table-toolbar">
        <SearchInput
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索姓名、组织或阶段"
        />
        <Select label="所属组织" value={org} onChange={(event) => setOrg(event.target.value)}>
          <option value="">所属组织</option>
          {orgOptions.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </Select>
        <div className="toolbar-spacer" />
        <span className="inline-note">当前列表只显示当前账号授权范围内的采集表。</span>
      </div>
      {error && <ErrorBox error={error} retry={() => setTick((value) => value + 1)} />}
      {loading ? (
        <Loading />
      ) : filtered.length ? (
        <div className="table-scroll">
          <table className="member-table member-info-table">
            <thead>
              <tr>
                <th>姓名</th>
                <th>所属组织</th>
                <th>人员类别</th>
                <th>状态</th>
                <th>版本</th>
                <th>最近更新</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr key={item.id}>
                  <td>
                    <button className="member-name" onClick={() => openDetail(item)}>
                      <span className="member-initial">{item.member_name?.[0] || "党"}</span>
                      {item.member_name}
                    </button>
                  </td>
                  <td className="org-cell">{item.org_name}</td>
                  <td>{item.member_stage_label || personCategory(item.member_stage)}</td>
                  <td>
                    <Badge tone={infoStatusTone(item.status)}>{infoStatusLabel(item.status)}</Badge>
                  </td>
                  <td>第 {item.version || 0} 版</td>
                  <td>{formatTime(item.updated_at)}</td>
                  <td>
                    <button className="text-button link" onClick={() => openDetail(item)}>
                      查看与办理
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty
          title={allItems.length ? "没有符合条件的采集表" : "当前范围暂无采集表"}
          description={
            allItems.length
              ? "请调整状态、组织或搜索关键词。"
              : "党员可在“本人档案”中填写基本信息采集表；提交后会进入这里。"
          }
        />
      )}

      {selected && (
        <Modal
          title="党员基本信息采集表"
          wide
          flat
          className="member-info-detail-modal"
          onClose={closeDetail}
        >
          {detailLoading && <Loading />}
          {detailError && <ErrorBox error={detailError} retry={() => openDetail({ id: selected })} />}
          {detail && !detailLoading && (
            <div className="member-info-detail">
              <div className="detail-profile member-archive-profile">
                <div className="large-member-avatar">{detail.member_name?.[0] || "党"}</div>
                <div className="member-archive-identity">
                  <h3>{detail.member_name}</h3>
                  <p>{detail.org_name}</p>
                </div>
                <Badge tone={infoStatusTone(detail.status)}>{infoStatusLabel(detail.status)}</Badge>
              </div>
              <div className="member-info-detail-meta">
                <span>第 {detail.version || 0} 版</span>
                <span>人员类别：{profile?.person_category}</span>
                <span>身份证号：{profile?.id_card_masked || "档案未登记"}</span>
              </div>
              <InfoSummary payload={detail.payload} profile={profile} />
              <PanelTitle title="流转记录" />
              <InfoTimeline collection={detail} />
              {detail.status === "returned" && detail.return_reason && (
                <div className="member-info-return">
                  <WarningCircle size={18} />
                  <div>
                    <strong>退回原因</strong>
                    <p>{detail.return_reason}</p>
                    <small>{detail.returned_by_name} · {formatTime(detail.returned_at)}</small>
                  </div>
                </div>
              )}
              <div className="modal-actions">
                <button className="button secondary" onClick={closeDetail}>
                  关闭
                </button>
                {IS_LIVE && (
                  <button className="button secondary" onClick={exportWord}>
                    导出 Word
                  </button>
                )}
                {canEdit && (
                  <button className="button secondary" onClick={() => setEditing(true)}>
                    <PencilSimple size={17} />
                    补录支部信息
                  </button>
                )}
                {canReview && (
                  <>
                    <button
                      className="button secondary"
                      onClick={() => {
                        setReview({ action: "return" });
                        setReviewOpinion("");
                        setReviewError(null);
                      }}
                    >
                      退回补正
                    </button>
                    <button
                      className="button primary"
                      onClick={() => {
                        setReview({ action: detail.status === "department_approved" ? "archive" : "approve" });
                        setReviewOpinion("");
                        setReviewError(null);
                      }}
                    >
                      {actionLabel}
                      <ArrowRight size={16} />
                    </button>
                  </>
                )}
              </div>
            </div>
          )}
        </Modal>
      )}

      {editing && detail && (
        <Modal title="支部补录与核对" wide flat onClose={() => setEditing(false)}>
          <MemberInfoForm
            mode="branch"
            profile={{ ...detail, stage: detail.member_stage }}
            collection={detail}
            initial={mergeBranchPayload(detail.payload, {})}
            onSave={saveBranch}
            onClose={() => setEditing(false)}
          />
        </Modal>
      )}

      {review && detail && (
        <Modal
          title={review.action === "return" ? "退回补正" : actionLabel}
          onClose={() => !reviewBusy && setReview(null)}
        >
          <p className="inline-note">
            {review.action === "return"
              ? "退回后本人可修改并重新提交；请写明需要补正的内容。"
              : review.action === "archive"
                ? "备案后当前版本成为只读归档件，请核对信息完整、审核意见齐全。"
                : "审核通过后进入下一环节；请核对全部信息。"}
          </p>
          <Field label="处理意见" required full>
            <textarea
              value={reviewOpinion}
              rows={4}
              maxLength={1000}
              onChange={(event) => setReviewOpinion(event.target.value)}
              placeholder="请填写核对情况、处理意见或退回原因"
            />
          </Field>
          {reviewError && <div className="info-form-error">{reviewError}</div>}
          <div className="modal-actions">
            <button className="button secondary" onClick={() => setReview(null)} disabled={reviewBusy}>
              取消
            </button>
            <button className="button primary" onClick={submitReview} disabled={reviewBusy}>
              {reviewBusy ? "正在处理…" : review.action === "return" ? "确认退回" : actionLabel}
            </button>
          </div>
        </Modal>
      )}
    </section>
  );
}
