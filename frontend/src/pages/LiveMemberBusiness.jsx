import { formatBusinessTime } from "../business-time";
import { useState } from "react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { hasPermission } from "../roles";
import { PageHeader, Tabs, Select, Modal, Pagination, downloadBlob } from "../components";
import { request } from "../api";
import { get, send, key, rows } from "../business-api";
import { BusinessForm, BusinessTable, RecordTrace, ResourceState, Status, options, useResource } from "../components/BusinessForms";

const stages = [["activist", "入党积极分子"], ["candidate", "发展对象"], ["probationary", "预备党员"], ["member", "正式党员"]];
const reason = { name: "reason", label: "办理依据与说明", type: "textarea" };

export function LiveMemberBusiness({ initialTab = "选优结论" }) {
  const { session } = useApp(), { notify } = useStore();
  const can = p => hasPermission(session, p);
  const [tab, setTab] = useState(initialTab), [page, setPage] = useState(1), [year, setYear] = useState(new Date().getFullYear()), [org, setOrg] = useState(""), [form, setForm] = useState(null), [selected, setSelected] = useState(null);
  const people = useResource(() => get("/member/roster", { page_size: 100 }), []);
  const orgs = useResource(() => get("/member/org-units"), []);
  const batches = useResource(() => get("/member-full/batches", { page_size: 100 }), []);
  const paths = { "选优结论": "/member-full/selections", "团组织推优": "/member-full/league-recommendations", "组织接转": "/member-full/transfers", "上级报送": "/member-full/upper-reports", "民主评议": "/meeting/member-reviews" };
  const path = paths[tab];
  const records = useResource(() => tab === "民主评议" ? get(path + "/workspace", { year, org_unit_id: org }) : get(path, { page, page_size: 20 }), [tab, page, org, year]);
  const detail = useResource(() => selected ? get(`${selected.path}/${key(selected.id)}`) : Promise.resolve(null), [selected?.path, selected?.id]);
  const list = tab === "民主评议" ? (records.value?.targets || []).map(r => ({ ...r, id: r.review_id || r.profile_id })) : rows(records.value);
  const personOptions = options(rows(people.value));
  const orgOptions = options(rows(orgs.value).filter(o => o.org_type === "branch"));
  const profile = { name: "profile_id", label: "本人档案", options: personOptions };
  function open(title, fields, submit, initial = {}, description) { setForm({ title, fields, submit, initial, description }); }
  async function save(url, body, method = "POST") { const result = await send(url, body, method); records.reload(); detail.reload(); people.reload(); batches.reload(); notify("业务记录已保存"); return result; }
  function selection(record) {
    open(record ? "修订拟推荐名单" : "登记选优结论草案", [
      ...(!record ? [{ name: "batch_no", label: "发展批次", options: rows(batches.value).map(b => [b.batch_no, `${b.batch_no} ${b.label}`]) }, { name: "round_no", label: "研究轮次", type: "number", min: 1, max: 20, value: 1 }] : []),
      { name: "target_stage", label: "拟推进阶段", options: stages }, { name: "candidate_ids", label: "拟推荐对象（多选）", type: "multi", options: personOptions },
      { name: "basis", label: "投票、材料及培养记录依据", type: "textarea" }, { name: "research_on", label: "研究日期", type: "date" },
      { name: "research_method", label: "研究程序", options: [["committee", "支委会研究"], ["member_meeting", "党员大会研究"]] }, reason,
    ], values => save(record ? `${path}/${key(record.id)}` : path, { ...values, ...(record ? { expected_revision: record.revision } : {}) }, record ? "PATCH" : "POST"), record ? { ...record, candidate_ids: record.candidates.map(c => c.profile_id) } : {}, "名单与依据由组织人员填写，系统保留过程证据；另一位有权限的人员审核通过后生效。");
  }
  function transfer() {
    open("登记组织关系接转", [
      { name: "direction", label: "接转方向", options: [["out", "转出"], ["in", "转入"]] },
      { ...profile, required: false, help: "转出必须关联档案；转入可关联既有档案，或填写下方新建信息" },
      { name: "org_unit_id", label: "转入接收支部", options: orgOptions, required: false }, { name: "name", label: "新建转入档案姓名", required: false, maxLength: 50 },
      { name: "current_stage", label: "新建转入阶段", options: stages.slice(2), required: false }, { name: "stage_joined_on", label: "进入该阶段日期", type: "date", required: false },
      { name: "counterpart_org", label: "对方组织全称", maxLength: 200 }, { name: "letter_no", label: "介绍信编号", maxLength: 64 },
      { name: "issued_on", label: "介绍信开具日期", type: "date" }, { name: "valid_until", label: "有效期至（可按制度默认）", type: "date", required: false },
      { name: "note", label: "说明", type: "textarea", required: false }, reason,
    ], values => save(path, Object.fromEntries(Object.entries(values).filter(([, v]) => v !== ""))), {}, "登记保留介绍信和回执事实。转入档案须核对材料，转出须回填接收回执；登记本身不会生成审批结论。");
  }
  function report() { open("登记上级审批或备案报送", [profile, { name: "item", label: "报送事项", options: [["activist_record", "积极分子备案"], ["candidate_record", "发展对象备案"], ["probationary_approval", "接收预备党员审批"], ["member_approval", "预备党员转正审批"]] }, { name: "upper_org", label: "上级党组织" }, { name: "letter_no", label: "报送文号", required: false, maxLength: 64 }, { name: "submitted_on", label: "报送日期", type: "date" }, { name: "note", label: "随报说明", type: "textarea", required: false }, reason], values => save(path, values), {}, "系统记录实际报送及上级批复事实；回填批复不替代上级审批，也不自动改变党员阶段。"); }
  function recommendation() { open("登记团组织推优", [profile, { name: "league_org", label: "推荐团组织" }, { name: "recommended_on", label: "推荐日期", type: "date" }, { name: "note", label: "推优说明", type: "textarea", required: false, max: 5000 }, reason], values => save(path, values)); }
  function editReview(record) {
    const procedure = record.procedure || {};
    open("登记民主评议程序与等次", [
      ...(!record.id ? [profile] : []),
      { name: "self_assessment", label: "个人自评", type: "textarea", max: 5000 }, { name: "peer_review", label: "党员互评汇总", type: "textarea", max: 5000 },
      ...[["eligible", "应参加人数"], ["attended", "实际参加人数"], ["outstanding", "优秀票数"], ["qualified", "合格票数"], ["basic", "基本合格票数"], ["unqualified", "不合格票数"]].map(([name, label]) => ({ name, label, type: "number", min: 0, max: 100000, value: procedure.test?.[name] || 0 })),
      { name: "branch_opinion", label: "支部评定意见", type: "textarea", max: 5000 }, { name: "grade", label: "拟评定等次", options: [["outstanding", "优秀"], ["qualified", "合格"], ["basic", "基本合格"], ["unqualified", "不合格"]] },
      { name: "basis", label: "评定依据", type: "textarea" }, { name: "rectification", label: "整改措施与要求", type: "textarea", required: false }, reason,
    ], values => {
      const { self_assessment, peer_review, branch_opinion, eligible, attended, outstanding, qualified, basic, unqualified, ...rest } = values;
      return save(record.id ? `${path}/${key(record.id)}` : path, { ...rest, procedure: { self_assessment, peer_review, branch_opinion, test: { eligible, attended, outstanding, qualified, basic, unqualified } }, ...(record.id ? { expected_revision: record.revision } : { year }) }, record.id ? "PATCH" : "POST");
    }, { ...record, ...procedure });
  }
  function submitReview(record, decision) {
    const action = decision ? "review" : "submit";
    open(decision ? "审核当前业务版本" : "提交当前版本审核", [...(decision ? [{ name: "decision", label: "审核结果", options: [["approved", "通过"], ["rejected", "退回补充"]] }] : []), reason], values => save(`${path}/${key(record.id)}/${action}`, { ...values, expected_revision: record.revision }));
  }
  function settle(record) {
    const isTransfer = tab === "组织接转";
    open(isTransfer ? "登记接转回执" : "回填上级批复事实", [
      ...(isTransfer ? [{ name: "settled_on", label: "回执日期", type: "date" }, { name: "receipt_no", label: "回执编号", maxLength: 64, required: false }, { name: "note", label: "档案核对 / 回执说明", type: "textarea", required: false }] : [
        { name: "result", label: "上级批复结果", options: [["agreed", "同意"], ["rejected", "不同意"], ["supplement", "补充材料"]] }, { name: "decided_on", label: "批复日期", type: "date" }, { name: "reply_no", label: "上级批复文号（同意或不同意必填）", required: false, maxLength: 64 }, { name: "decide_note", label: "批复意见 / 待补材料", type: "textarea", required: false },
      ]), reason,
    ], values => save(`${path}/${key(record.id)}/settle`, values));
  }
  function revoke(record) { open("作废当前登记并保留留痕", [reason], values => save(`${path}/${key(record.id)}/revoke`, values)); }
  function createBatch() { open("登记发展批次", [{ name: "batch_no", label: "批次编号", maxLength: 20 }, { name: "label", label: "批次名称", maxLength: 200 }, { name: "year", label: "年度", type: "number", min: 2000, max: 2100, value: year }, { name: "org_unit_id", label: "归属支部", options: orgOptions }, reason], values => save("/member-full/batches", values)); }
  function vote() { open("登记本人研究投票", [{ name: "batch_no", label: "批次", options: rows(batches.value).map(b => [b.batch_no, b.label]) }, { name: "round_no", label: "轮次", type: "number", min: 1, max: 20, value: 1 }, profile, { name: "vote", label: "本人投票意见", options: [["agree", "同意"], ["disagree", "不同意"], ["abstain", "弃权"]] }, { name: "comment", label: "说明", type: "textarea", required: false, max: 500 }], values => { const { batch_no, round_no, ...entry } = values; return save("/member-full/votes", { batch_no, round_no, votes: [entry] }); }); }
  const d = detail.value;
  return <section className="panel workspace-panel"><PageHeader title="组织业务办理" subtitle="选优、民主评议、组织关系与上级报送业务台账" />
    <Tabs items={Object.keys(paths)} active={tab} onChange={value => { setTab(value); setPage(1); setSelected(null); }} />
    <div className="business-toolbar">{tab === "民主评议" && <><Select label="评议年度" value={year} onChange={e => setYear(Number(e.target.value))}>{Array.from({ length: 6 }, (_, i) => new Date().getFullYear() - i).map(y => <option key={y}>{y}</option>)}</Select><Select label="评议支部" value={org} onChange={e => setOrg(e.target.value)}><option value="">全部授权组织</option>{orgOptions.map(([id, name]) => <option value={id} key={id}>{name}</option>)}</Select>{can("meeting.manage") && <button className="button primary" onClick={() => open("发起年度民主评议", [{ name: "org_unit_id", label: "评议支部", options: orgOptions, value: org }, reason], values => save(path + "/launch", { ...values, year }))}>按支部发起</button>}</>}
      {tab === "选优结论" && can("member.scoring") && <><button className="button primary" onClick={() => selection()}>登记拟推荐名单</button><button className="button secondary" onClick={vote}>登记本人投票</button>{can("member.stage_transition") && <button className="button secondary" onClick={createBatch}>登记发展批次</button>}</>}
      {tab === "团组织推优" && can("member.scoring") && <button className="button primary" onClick={recommendation}>登记推优</button>}
      {tab === "组织接转" && can("member.stage_transition") && <button className="button primary" onClick={transfer}>登记接转</button>}
      {tab === "上级报送" && can("member.stage_transition") && <button className="button primary" onClick={report}>登记报送</button>}
      {tab === "上级报送" && <button className="button secondary" onClick={() => open("导出报送台账", [reason], async () => downloadBlob(await request("/member-full/upper-reports/export", { download: true }), "上级报送台账.xlsx"))}>导出台账</button>}
      <button className="button secondary" onClick={records.reload}>刷新</button>
    </div><ResourceState resource={records} /><ResourceState resource={people} /><ResourceState resource={orgs} />
    <BusinessTable items={list} columns={[["业务对象", r => r.member_name || (r.candidates || []).map(c => c.name || c.member_name).join("、") || r.profile_id], ["组织 / 批次", r => [r.org_name, r.batch_no].filter(Boolean).join(" · ") || "—"], ["办理事项", r => r.item_label || r.target_stage_label || r.grade_label || (tab === "民主评议" ? "评议等次待定" : r.direction === "in" ? "转入" : r.direction === "out" ? "转出" : "团组织推优")], ["状态", r => <Status value={tab === "团组织推优" ? r.active ? "recorded" : "revoked" : r.review_status || r.status || "planned"} />], ["操作", r => tab === "团组织推优" ? can("member.scoring") && r.active !== false && <button className="text-button link" onClick={() => revoke(r)}>作废</button> : r.review_id || tab !== "民主评议" ? <button className="text-button link" onClick={() => setSelected({ path, id: r.review_id || r.id })}>查看与办理</button> : can("meeting.manage") && <button className="text-button link" onClick={() => editReview({ profile_id: r.profile_id })}>建立评议记录</button>]]} />
    {tab !== "民主评议" && <Pagination page={page} pages={Math.max(1, Math.ceil((records.value?.total || 0) / 20))} total={records.value?.total || 0} onChange={setPage} />}
    {tab === "民主评议" && records.value && <p className="inline-note">应评议{records.value.target_total}人；优秀比例{records.value.outstanding_ratio}%。{records.value.notices?.outstanding_notice}</p>}
    {selected && <Modal title={`${tab}办理详情`} wide flat onClose={() => setSelected(null)}><ResourceState resource={detail} />{d && <><h3>{d.member_name || d.org_name || d.batch_no}</h3><Status value={d.review_status || d.status} /><RecordTrace record={d} /><div className="business-content">{d.basis || d.note || d.reason}</div>{d.candidates && <p>拟推荐名单：{d.candidates.map(c => c.name || c.member_name).join("、")}</p>}{d.procedure && <><p>个人自评：{d.procedure.self_assessment}</p><p>党员互评：{d.procedure.peer_review}</p><p>支部意见：{d.procedure.branch_opinion}</p><p>等次：{d.grade_label}；整改：{d.rectification || "—"}</p></>}{d.counterpart_org && <p>对方组织：{d.counterpart_org}；介绍信：{d.letter_no}；有效期：{d.valid_until}</p>}{d.upper_org && <p>报送组织：{d.upper_org}；批复文号：{d.reply_no || "未回填"}；批复意见：{d.decide_note || "—"}</p>}{d.missing?.length > 0 && <p className="inline-note">{d.missing.join("；")}</p>}<p>{d.notice}</p>
      <div className="business-actions">{["选优结论", "民主评议"].includes(tab) && <>{can(tab === "选优结论" ? "member.scoring" : "meeting.manage") && <><button className="button secondary" onClick={() => tab === "选优结论" ? selection(d) : editReview(d)}>修订当前记录</button>{["draft", "rejected"].includes(d.review_status) && <button className="button primary" onClick={() => submitReview(d)}>提交审核</button>}</>}{d.review_status === "pending" && d.submitted_by !== session.user.id && can(tab === "选优结论" ? "member.stage_transition" : "meeting.review") && <button className="button primary" onClick={() => submitReview(d, true)}>人工审核</button>}</>}
        {["组织接转", "上级报送"].includes(tab) && can("member.stage_transition") && <>{["pending", "submitted"].includes(d.status) && <button className="button primary" onClick={() => settle(d)}>{tab === "组织接转" ? "登记回执" : "回填批复"}</button>}{d.status !== "revoked" && <button className="button secondary" onClick={() => revoke(d)}>作废登记</button>}</>}
      </div><h4>办理与修订留痕</h4><BusinessTable items={d.revisions || d.history || []} columns={[["版本", r => r.revision], ["操作", r => r.action], ["办理人", r => r.actor_id || r.created_by], ["说明", r => r.reason], ["时间", r => formatBusinessTime(r.created_at)]]} />
    </>}</Modal>}
    {form && <BusinessForm key={form.title} {...form} onSubmit={form.submit} onClose={() => setForm(null)} />}
  </section>;
}
