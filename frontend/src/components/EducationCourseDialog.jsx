import { useEffect, useRef, useState } from "react";
import { CaretLeft, CaretRight, Clock } from "@phosphor-icons/react";
import { ErrorBox, Field, Modal, Tabs } from "../components";
import { ResourceState } from "./BusinessForms";
import { educationNotes, hasEducationNotes, videoRequirementMet } from "../education-local";
import "../education-course.css";

function readingBlocks(text) {
  const blocks = [];
  for (const line of String(text || "").split(/\r?\n/).map(line => line.trim()).filter(Boolean)) {
    const item = /^(\d+)[.、．]\s*(.+)$/.exec(line);
    if (item) {
      if (blocks.at(-1)?.kind !== "list") blocks.push({ kind: "list", items: [] });
      blocks.at(-1).items.push({ number: item[1], text: item[2] });
    } else blocks.push({ kind: /^(?:#{1,3}\s+|[一二三四五六七八九十]+[、．.])/.test(line) ? "heading" : "paragraph", text: line.replace(/^#{1,3}\s+/, "") });
  }
  return blocks.map((block, index) => block.kind === "heading" ? <h3 key={index}>{block.text}</h3>
    : block.kind === "list" ? <ol className="education-reading-questions" role="list" key={index}>{block.items.map((item, itemIndex) => <li key={itemIndex} value={Number(item.number)}><span className="education-reading-number" aria-hidden="true">{item.number}</span><span>{item.text}</span></li>)}</ol>
    : <p key={index}>{block.text}</p>);
}

const answerLabel = (question, index) => index == null ? "此前未保存逐题作答记录" : `${String.fromCharCode(65 + index)}. ${question.options[index]}`;

function ExamReview({ progress }) {
  if (!progress?.attempts) return null;
  return <section className="education-exam-review" aria-label="测评答案与解析">
    <header><h3>测评结果与解析</h3><p role="status">第 {progress.attempts} 次测评 · {progress.score} 分 · {progress.passed ? "已通过" : "未通过"}</p></header>
    {progress.exam_review?.length ? progress.exam_review.map((question, index) => <article className="education-review-question" key={question.id}>
      <h4>{index + 1}. {question.text}<span className={`education-answer-state ${question.correct == null ? "unknown" : question.correct ? "correct" : "incorrect"}`}>{question.correct == null ? "历史记录" : question.correct ? "回答正确" : "回答错误"}</span></h4>
      <p>本人答案：{answerLabel(question, question.selected_index)}</p>
      <p className="education-correct-answer">正确答案：{answerLabel(question, question.correct_index)}</p>
      <div className="education-answer-explanation"><strong>解析</strong><p>{question.explanation || "发布组织尚未提供本题解析，请结合正确答案复习课程内容。"}</p></div>
    </article>) : <p className="education-course-notice">此前测评未保存逐题作答记录，当前仅能查阅已保存的成绩。</p>}
  </section>;
}

export function EducationCourseDialog({ course, resource, progress, error, onClose, enrollBusy, onEnroll, onPublish, notes, setNote, savingNote, onSaveNote, examBusy, onExam, videoRef, onHeartbeat, videoError, onVideoError, management }) {
  const [tab, setTab] = useState("学习内容"), [materialIndex, setMaterialIndex] = useState(0);
  const content = course?.content || {}, questions = content.questions || [];
  const reading = String(content.reading_text || content.description || "").trim();
  const materials = [
    ...(reading ? [{ id: "reading", title: content.reading_text ? "学习导读" : "学习说明" }] : []),
    ...(content.video_url ? [{ id: "lesson", title: "课程内容" }] : []),
  ];
  const currentIndex = Math.min(materialIndex, Math.max(0, materials.length - 1));
  const currentMaterial = materials[currentIndex];
  const savedNotes = educationNotes(progress), note = notes[currentMaterial?.id] || "";
  const savedNote = savedNotes[currentMaterial?.id] || "", noteDirty = note !== savedNote;
  const anyNoteDirty = materials.some(material => (notes[material.id] || "") !== (savedNotes[material.id] || ""));
  const started = !!progress && progress.status !== "cancelled", completed = progress?.status === "completed";
  const canStudy = course?.status === "published", busy = examBusy || savingNote || enrollBusy;
  const examDisabled = !started || busy || completed || !videoRequirementMet({ content }, progress) || (progress?.attempts || 0) >= content.max_attempts;
  const contentPane = useRef(null);
  const noteInput = useRef(null);
  useEffect(() => { if (tab === "本人笔记" && started) noteInput.current?.focus(); }, [tab, currentMaterial?.id, started]);
  useEffect(() => { if (progress?.attempts && contentPane.current) contentPane.current.scrollTop = 0; }, [progress?.attempts]);
  function pause() {
    if (videoRef.current && !videoRef.current.paused) { onHeartbeat(true); videoRef.current.pause(); }
  }
  function changeTab(value) {
    if (value !== "学习内容") pause();
    setTab(value);
    if (contentPane.current) contentPane.current.scrollTop = 0;
  }
  function changeMaterial(value) {
    pause(); setMaterialIndex(value);
    if (contentPane.current) contentPane.current.scrollTop = 0;
  }
  const publisher = course?.org_unit_name || "所属组织发布";
  return <Modal title="课程学习" wide flat className="education-detail education-course-dialog" onClose={onClose}>
    {course ? <>
      <header className="education-course-heading">
        <h2>{course.title}</h2>
        <p>{publisher}<span>·</span>{course.status === "draft" ? "草稿" : completed ? "已完成" : started ? "学习中" : "未开始"}<span>·</span>{completed ? `本人已获得 ${progress.points} 积分` : `完成后 ${content.points} 积分`}</p>
      </header>
      <Tabs items={["学习内容", "课程测评", { id: "本人笔记", label: <span className="education-notes-tab">本人笔记{(anyNoteDirty || hasEducationNotes(progress)) && <small className={`education-note-tag${anyNoteDirty ? " unsaved" : ""}`}>{anyNoteDirty ? "未保存" : "有笔记"}</small>}</span> }, ...(course.can_manage ? ["组织学习进度"] : [])]} active={tab} onChange={changeTab} />
      <div className="education-course-scroll" ref={contentPane}>
        {error && <ErrorBox error={error} />}
        <section className="education-course-pane" hidden={tab !== "学习内容"} aria-label="学习内容">
          {materials.length > 0 && <div className="education-material-toolbar"><h3>{currentMaterial.title}{savedNote.trim() && <span className="education-note-tag">有笔记</span>}</h3><div><button className="icon-button" aria-label="上一份学习资料" disabled={currentIndex === 0} onClick={() => changeMaterial(currentIndex - 1)}><CaretLeft size={18} /></button><span>第 {currentIndex + 1} 份 / 共 {materials.length} 份</span><button className="icon-button" aria-label="下一份学习资料" disabled={currentIndex + 1 >= materials.length} onClick={() => changeMaterial(currentIndex + 1)}><CaretRight size={18} /></button></div></div>}
          <article className="education-reading-article" hidden={currentMaterial?.id !== "reading"}>
            <h2>{content.reading_text ? "专题学习导读" : "课程学习说明"}</h2>
            <div className="education-reading-body">{readingBlocks(reading)}</div>
          </article>
          {content.video_url && <section className="education-video-pane" hidden={currentMaterial?.id !== "lesson"}>
            {started ? <>
              <video key={course.id} ref={videoRef} className="business-video" controls preload="metadata" src={content.video_url} onLoadedMetadata={() => { if (videoRef.current && progress.position_seconds) videoRef.current.currentTime = progress.position_seconds; }} onTimeUpdate={() => onHeartbeat()} onPause={() => onHeartbeat(true)} onEnded={() => onHeartbeat(true)} onError={onVideoError} />
              {videoError && <p className="education-video-error" role="alert">课程内容暂时无法播放，请检查网络；如持续失败，请联系发布组织核对资源地址。学习进度以已保存记录为准。</p>}
              <p className="education-help"><Clock size={15} />有效学习 {Math.floor(progress.watched_seconds || 0)} / {content.duration_seconds} 秒；正常播放时定期保存，拖动进度不计作完成学习。</p>
            </> : <p className="education-course-notice">开始本次学习后即可查看课程内容并记录本人进度。</p>}
          </section>}
          {!materials.length && <p className="education-course-notice">当前课程尚未提供可查阅的学习内容，请联系发布组织核对。</p>}
        </section>
        <section className="education-course-pane education-assessment-pane" hidden={tab !== "课程测评"} aria-label="课程测评">
          {completed && <div className="education-completed"><h3>本课程已完成</h3><p>{progress.score != null && `最近成绩 ${progress.score} 分，`}本人已获得 {progress.points} 积分。</p></div>}
          <ExamReview progress={progress} />
          {!completed && (questions.length ? <form id={`education-exam-${course.id}`} className="education-exam" onSubmit={onExam}>
            <h3>课程测评</h3><p>合格分数 {content.passing_score}；已使用 {progress?.attempts || 0} / {content.max_attempts} 次。</p>
            {!started && <p className="education-course-notice">开始本次学习后可以参加课程测评。</p>}
            {started && !videoRequirementMet(course, progress) && <p className="education-course-notice">请先完成课程内容学习，再参加测评。</p>}
            <fieldset disabled={examDisabled}>{questions.map((question, index) => <fieldset className="education-question" key={question.id}>
              <legend><span aria-hidden="true">*</span>{index + 1}. {question.text}</legend>
              <div className="education-options">{question.options.map((label, value) => <label key={value}><input type="radio" name={question.id} value={value} required /><span>{label}</span></label>)}</div>
            </fieldset>)}</fieldset>
          </form> : <p className="education-course-notice">当前课程未设置测评，请按课程要求完成学习。</p>)}
        </section>
        <section className="education-course-pane education-notes-pane" hidden={tab !== "本人笔记"} aria-label="本人笔记">
          <header><h3>本人笔记</h3><p>仅本人可见，可在此记录学习体会与需要进一步核对的问题。</p></header>
          <div className="education-note-chapters" role="group" aria-label="笔记所属章节">{materials.map((material, index) => <button type="button" key={material.id} className="education-note-chapter" aria-pressed={currentIndex === index} onClick={() => changeMaterial(index)}>第 {index + 1} 份 · {material.title}{String(savedNotes[material.id] || "").trim() && <span className="education-note-tag">有笔记</span>}</button>)}</div>
          {!started && <p className="education-course-notice">开始本次学习后可以保存本人笔记。</p>}
          <div className="education-note-feedback"><p role="status">{savingNote ? "正在保存当前章节笔记…" : noteDirty ? "当前章节笔记尚未保存。" : savedNote.trim() ? "当前章节笔记已保存，仅本人可见。" : "当前章节暂无笔记。"}</p><p className="education-note-count">{note.length} / 5000</p></div>
          <Field label={currentMaterial ? `${currentMaterial.title} · 我的学习笔记` : "我的学习笔记"}><textarea ref={noteInput} rows={12} maxLength={5000} disabled={!started || busy || !currentMaterial} value={note} onChange={event => setNote(currentMaterial.id, event.target.value)} placeholder="记录个人学习体会与需要进一步核对的问题" /></Field>
        </section>
        {course.can_manage && <section className="education-course-pane education-management-pane" hidden={tab !== "组织学习进度"} aria-label="组织学习进度">{management}</section>}
      </div>
      <footer className="education-course-footer">
        <button className="text-button education-return" onClick={onClose}><CaretLeft size={16} />返回课程</button>
        <div className="education-material-pager" hidden={tab !== "学习内容"}><button className="button secondary" disabled={!materials.length || currentIndex === 0} onClick={() => changeMaterial(currentIndex - 1)}><CaretLeft size={16} />上一份</button><button className="button secondary" disabled={currentIndex + 1 >= materials.length} onClick={() => changeMaterial(currentIndex + 1)}>下一份<CaretRight size={16} /></button></div>
        <div className="education-course-primary">
          {course.status === "draft" && course.can_manage ? <button className="button primary" onClick={onPublish}>确认发布</button> : canStudy && !started ? <button className="button primary" disabled={busy} onClick={onEnroll}>{enrollBusy ? "正在办理…" : "开始本次学习"}</button> : tab === "本人笔记" ? <button className="button primary" disabled={!started || busy || !currentMaterial} onClick={() => onSaveNote(currentMaterial.id)}>{savingNote ? "正在保存…" : "保存本人笔记"}</button> : tab === "课程测评" && !completed && questions.length ? <button className="button primary" type="submit" form={`education-exam-${course.id}`} disabled={examDisabled}>{examBusy ? "正在提交…" : (progress?.attempts || 0) >= content.max_attempts ? "考试次数已用完" : "提交考试"}</button> : tab === "学习内容" ? <><button className="button secondary" onClick={() => changeTab("本人笔记")}>记录笔记</button>{questions.length > 0 && <button className="button primary" onClick={() => changeTab("课程测评")}>{completed ? "查看测评" : "进入测评"}</button>}</> : <button className="button secondary" onClick={() => changeTab("学习内容")}>返回学习内容</button>}
        </div>
      </footer>
    </> : <div className="education-course-loading"><ResourceState resource={resource} /></div>}
  </Modal>;
}
