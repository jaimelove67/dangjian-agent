import { BookOpen, ArrowRight } from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { rows } from "../business-api";
import { useEducationApi } from "../education-api";
import { hasEducationNotes } from "../education-local";
import { PanelTitle, Badge, Empty, ErrorBox, Loading } from "../components";
import { useResource } from "./BusinessForms";
import "../education.css";

export function HomeLearning() {
  const { navigate } = useApp();
  const api = useEducationApi();
  const courses = useResource(() => api.get("/education/offerings", { kind: "course" }), [api.identity, api.revision]);
  const credits = useResource(() => api.get("/education/credits"), [api.identity, api.revision]);
  const published = rows(courses.value).filter(row => row.status === "published");
  const studying = published.filter(row => row.own?.status === "enrolled");
  const featured = [...studying, ...published.filter(row => !studying.some(item => item.id === row.id))].slice(0, 2);
  return <section className="panel home-learning" aria-label="我的学习">
    <PanelTitle title="我的学习" action="全部课程" onAction={() => navigate("learning")} />
    <div className="home-learning-summary"><span>学习中 <strong>{courses.loading || courses.error ? "—" : studying.length}</strong></span><span>已完成 <strong>{courses.loading || courses.error ? "—" : published.filter(row => row.own?.status === "completed").length}</strong></span><button onClick={() => navigate("learning", { tab: "我的积分" })}>本人积分 <strong>{credits.loading || credits.error ? "—" : credits.value?.total_points ?? 0}</strong><ArrowRight size={13} /></button></div>
    {courses.loading && <Loading />}{courses.error && <ErrorBox error={courses.error} retry={courses.reload} />}{credits.error && <ErrorBox error={credits.error} retry={credits.reload} />}
    {featured.map(course => <button className="home-action-row" key={course.id} onClick={() => navigate("learning", { offeringId: course.id })}><span className="home-row-icon"><BookOpen size={21} /></span><span><strong>{course.title}</strong><small>{course.own?.status === "completed" ? "课程已完成" : course.own ? "继续本人学习" : "按组织发布要求开展学习"} · {course.content.points} 积分{hasEducationNotes(course.own) && <span className="education-note-tag">有笔记</span>}</small></span><Badge tone={course.own?.status === "completed" ? "green" : "blue"}>{course.own?.status === "completed" ? "已完成" : course.own ? "继续" : "学习"}</Badge></button>)}
    {!courses.loading && !courses.error && !featured.length && <Empty title="暂无已发布课程" description="所属组织发布课程后，可在这里开始学习。" />}
  </section>;
}
