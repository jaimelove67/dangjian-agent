import { useEffect, useState } from "react";
import { BookOpen, CalendarBlank, CaretLeft, CaretRight, Coins, Info } from "@phosphor-icons/react";
import { Badge, SearchInput, Select } from "../components";
import { ResourceState } from "./BusinessForms";
import { rows } from "../business-api";
import { formatBusinessTime } from "../business-time";
import { hasEducationNotes } from "../education-local";

const PAGE_SIZE = 3;
const states = [["", "全部"], ["enrolled", "学习中"], ["not_started", "未开始"], ["completed", "已完成"]];
const stateOf = course => !course.own || course.own.status === "cancelled" ? "not_started" : course.own.status;
const COURSE_COVER = "/assets/learning-campus-autumn.webp";
const dateOf = value => formatBusinessTime(value).slice(0, 10);

function CourseRow({ course, resume = false, onSelect }) {
  const state = stateOf(course), label = states.find(([id]) => id === state)?.[1] || "未开始";
  const action = state === "completed" ? "查看记录" : state === "enrolled" ? "继续学习" : "开始学习";
  return <article className={`education-course-row${resume ? " education-resume-row" : ""}`}>
    <img className="education-course-cover" src={COURSE_COVER} alt="" loading="lazy" />
    <div className="education-course-copy">
      <h3><button onClick={() => onSelect(course.id)}>{course.title}</button></h3>
      <p className="education-course-description">{course.content.description}</p>
      <p className="education-course-meta">{course.org_unit_name || "所属组织发布"}{resume && <><span aria-hidden="true"> · </span><span className="education-resume-status">学习中</span></>}{hasEducationNotes(course.own) && <span className="education-note-tag">有笔记</span>}</p>
    </div>
    <div className="education-course-actions">
      {!resume && <Badge tone={state === "completed" ? "green" : "orange"}>{label}</Badge>}
      <button className={`button ${state === "completed" || resume ? "secondary" : "primary"}`} onClick={() => onSelect(course.id)}>{action}</button>
    </div>
  </article>;
}

export function EducationLearnerWorkspace({ offerings, credits, events, query, setQuery, filter, setFilter, onSelect, onTab }) {
  const [page, setPage] = useState(0);
  const courses = rows(offerings.value).filter(course => course.status === "published");
  const available = !offerings.loading && !offerings.error;
  const filtered = courses.filter(course => (!query.trim() || course.title.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) && (!filter || stateOf(course) === filter));
  const pageCount = Math.ceil(filtered.length / PAGE_SIZE), currentPage = Math.min(page, Math.max(0, pageCount - 1));
  const continuing = courses.filter(course => stateOf(course) === "enrolled").slice(0, 2);
  const courseById = new Map(courses.map(course => [course.id, course]));
  const recent = rows(credits.value).filter(item => courseById.has(item.offering_id)).sort((a, b) => (Date.parse(b.completed_at) || 0) - (Date.parse(a.completed_at) || 0)).slice(0, 3);
  const registered = rows(events.value).filter(event => event.status === "published" && event.own?.status === "enrolled").sort((a, b) => Date.parse(a.content.starts_at) - Date.parse(b.content.starts_at));
  useEffect(() => setPage(0), [query, filter]);
  const counts = state => available ? courses.filter(course => !state || stateOf(course) === state).length : "—";
  return <div className="education-learner-grid">
    <div className="education-learner-main">
      <section className="panel education-learning-panel education-continue">
        <header className="education-section-heading"><h2>继续学习</h2></header>
        <ResourceState resource={offerings} />
        {available && (continuing.length ? continuing.map(course => <CourseRow key={course.id} course={course} resume onSelect={onSelect} />) : <p className="education-empty">暂无进行中的课程，可以从下方选择课程开始学习。</p>)}
      </section>
      <section className="panel education-learning-panel education-all-courses">
        <header className="education-section-heading education-catalog-heading">
          <h2>全部课程</h2>
          <div className="education-catalog-tools"><SearchInput placeholder="搜索课程名称" value={query} onChange={event => setQuery(event.target.value)} /><Select label="本人学习状态" value={filter} onChange={event => setFilter(event.target.value)}>{states.map(([id, label]) => <option key={id} value={id}>{id ? label : "全部状态"}</option>)}</Select></div>
        </header>
        <div className="education-state-tabs" role="tablist" aria-label="筛选课程状态">{states.map(([state, label]) => <button key={state} role="tab" aria-selected={filter === state} className={filter === state ? "active" : ""} onClick={() => setFilter(state)}>{label}<span>{counts(state)}</span></button>)}</div>
        {available && (filtered.length ? <>
          <div className="education-course-list">{filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE).map(course => <CourseRow key={course.id} course={course} onSelect={onSelect} />)}</div>
          {pageCount > 1 && <div className="education-pagination"><span>共 {filtered.length} 门课程</span><div><button className="icon-button" aria-label="上一页课程" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}><CaretLeft size={16} /></button><span>{currentPage + 1} / {pageCount}</span><button className="icon-button" aria-label="下一页课程" disabled={currentPage + 1 >= pageCount} onClick={() => setPage(currentPage + 1)}><CaretRight size={16} /></button></div></div>}
        </> : <p className="education-empty">{query.trim() || filter ? "没有符合当前条件的课程。" : "所属组织尚未发布可查阅的课程。"}</p>)}
      </section>
    </div>
    <aside className="panel education-learning-panel education-learning-records" aria-label="本人学习记录">
      <header className="education-section-heading"><h2>本人学习记录</h2></header>
      <div className="education-record-summary">
        <button onClick={() => { setFilter("completed"); setQuery(""); }}><span className="education-record-icon"><BookOpen size={28} /></span><span>已完成<strong>{counts("completed")}<small>门</small></strong></span></button>
        <button onClick={() => onTab("我的积分")}><span className="education-record-icon"><Coins size={28} /></span><span>本人积分<strong>{credits.loading || credits.error ? "—" : credits.value?.total_points ?? 0}<small>分</small></strong></span></button>
      </div>
      <section className="education-record-section education-recent">
        <header className="education-section-heading"><h3>最近完成</h3><button className="text-button" onClick={() => onTab("我的积分")}>查看更多<CaretRight size={14} /></button></header>
        <ResourceState resource={credits} />
        {offerings.error && !credits.error && <p className="education-empty">课程记录暂时无法读取，请在左侧重试课程请求。</p>}
        {available && !credits.loading && !credits.error && (recent.length ? <div>{recent.map(item => <button className="education-recent-row" key={item.id} onClick={() => onSelect(item.offering_id)}><img src={COURSE_COVER} alt="" /><span><strong>{item.title}</strong><time>{dateOf(item.completed_at)}</time></span><small>+{item.points}积分</small></button>)}</div> : <p className="education-empty">暂无已完成课程。</p>)}
      </section>
      <section className="education-record-section education-enrolled-events">
        <header className="education-section-heading"><h3>已报名活动</h3><button className="text-button" onClick={() => onTab("主题党日")}>查看更多<CaretRight size={14} /></button></header>
        <ResourceState resource={events} />
        {!events.loading && !events.error && (registered.length ? registered.slice(0, 2).map(event => <button className="education-event-row" key={event.id} onClick={() => onSelect(event.id)}><CalendarBlank size={30} /><span><strong>{event.title}</strong><time>{formatBusinessTime(event.content.starts_at).slice(0, 16)}</time></span><span className="education-event-action">查看活动<CaretRight size={14} /></span></button>) : <p className="education-empty">暂无已报名活动。<button className="text-button" onClick={() => onTab("主题党日")}>查看可报名活动<CaretRight size={14} /></button></p>)}
      </section>
      <p className="education-record-privacy"><Info size={16} />学习记录按本人账号保存。</p>
    </aside>
  </div>;
}
