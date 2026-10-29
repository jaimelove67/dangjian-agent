import { useState } from "react";
import { ArrowRight, BookOpen, CalendarBlank, FileText, IdentificationCard, Sparkle } from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE } from "../api";
import { get, rows } from "../business-api";
import { Badge, Empty, ErrorBox, Loading, Modal, PanelTitle } from "../components";
import { useResource } from "./BusinessForms";
import "../home-workspace.css";

export function HomeBanner({ title, description, stage, personal = false }) {
  const { session } = useApp();
  return <header className="home-banner">
    <div><h1>{title}</h1><p>{session.user.name}，您好。<span>{description}</span>{stage && <Badge tone="red">{stage}</Badge>}</p></div>
    <span className="home-banner-motto">{personal ? "学思践悟　知行合一" : "立校为党育人　为国育才"}</span>
  </header>;
}

export function HomeAssistant() {
  const { navigate } = useApp();
  return <section className="panel home-assistant"><PanelTitle title="制度问答" /><p>查制度依据，了解办理要求。</p><button className="button secondary" onClick={() => navigate("assistant")}><Sparkle size={18} />向党建智能体提问<ArrowRight size={16} /></button></section>;
}

export function OwnHomeTasks({ materials = [] }) {
  const { session, navigate } = useApp();
  const { data } = useStore();
  const [selected, setSelected] = useState(null);
  const resource = useResource(() => IS_LIVE ? get("/school/business/records", { kind: "task" }) : Promise.resolve(null), [session.user.id, session.user.tenant_id, session.user.org_unit_id, session.user.role]);
  const tasks = IS_LIVE ? rows(resource.value).filter(r => r.body?.assignee_id === session.user.id && ["assigned", "rejected"].includes(r.status)) : [];
  const missingFiles = materials.filter(m => m.has_file === false);
  const meetings = !IS_LIVE ? (data.meetings || []).filter(m => (m.tenant_id || "school-1") === session.user.tenant_id && m.orgId === session.user.org_unit_id && m.date >= new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Shanghai" }) && !["已归档", "已完成"].includes(m.status)).slice(0, 1) : [];
  return <section className="panel home-own-tasks">
    <PanelTitle title="我的事项"><span className="home-task-count">{IS_LIVE && (resource.loading || resource.error) ? "—" : tasks.length + missingFiles.length + meetings.length} 项</span></PanelTitle>
    {IS_LIVE && resource.loading && <Loading />}
    {IS_LIVE && resource.error && <ErrorBox error={resource.error} retry={resource.reload} />}
    {tasks.slice(0, 3).map(task => <button className="home-action-row" key={task.id} onClick={() => setSelected(task)}><span className="home-row-icon"><FileText size={21} /></span><span><strong>{task.title}</strong><small>{task.body.due_date || "未设期限"} · {task.status === "rejected" ? "退回补充" : "待办理"}</small></span><ArrowRight size={16} /></button>)}
    {missingFiles.slice(0, 2).map(material => <button className="home-action-row" key={material.id} onClick={() => navigate("self-materials")}><span className="home-row-icon"><FileText size={21} /></span><span><strong>补充材料原件</strong><small>{material.title} · 已登记，原件待提交</small></span><span className="home-row-link">去提交</span></button>)}
    {meetings.map(meeting => <button className="home-action-row" key={meeting.id} onClick={() => setSelected(meeting)}><span className="home-row-icon"><CalendarBlank size={21} /></span><span><strong>{meeting.title}</strong><small>{meeting.date} · 所属支部活动</small></span><ArrowRight size={16} /></button>)}
    {!tasks.length && !missingFiles.length && !meetings.length && (!IS_LIVE || (!resource.loading && !resource.error)) && <Empty title="当前暂无待办事项" description="组织下发的本人任务会显示在这里。" />}
    {materials[0] && <button className="home-action-row" onClick={() => navigate("self-materials")}><span className="home-row-icon"><BookOpen size={21} /></span><span><strong>最近提交记录</strong><small>{materials[0].title} · 个人提交</small></span><ArrowRight size={16} /></button>}
    {selected && <Modal title="本人事项" wide flat onClose={() => setSelected(null)}><h2>{selected.title}</h2><p className="body-copy">{selected.body?.requirements || selected.agenda || "具体安排请以所属组织通知为准。"}</p><p>{selected.body?.due_date ? `截止日期：${selected.body.due_date}` : selected.date}</p>{selected.location && <p>地点：{selected.location}</p>}{IS_LIVE && <button className="button primary" onClick={() => { setSelected(null); navigate("dashboard", { workspace: "tasks", recordId: selected.id }); }}>进入任务办理<ArrowRight size={16} /></button>}</Modal>}
  </section>;
}

export function OwnHomeArchive({ profile, loading, applicant }) {
  const { navigate, session } = useApp();
  return <section className="panel home-own-archive"><PanelTitle title={applicant ? "申请与培养进度" : "本人档案"} action="查看本人档案" onAction={() => navigate("self-archive")} />
    {loading ? <Loading /> : profile ? <button className="home-identity" onClick={() => navigate("self-archive")}><IdentificationCard size={36} /><span><strong>{profile.name || session.user.name}<Badge tone="red">{profile.stage}</Badge></strong><small>{profile.organization || "所属组织待登记"}</small>{applicant && <small>当前阶段以组织登记为准</small>}</span><ArrowRight size={16} /></button> : <Empty title="档案尚未关联" description="请联系所属支部组织员关联本人档案。" />}
  </section>;
}
