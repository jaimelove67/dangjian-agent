import { useState, useEffect } from "react";
import {
  UsersThree,
  TreeStructure,
  GraduationCap,
  ClipboardText,
  ArrowUpRight,
  Sparkle,
  ShieldCheck,
  PencilLine,
  ChartBar,
  FileText,
  CalendarBlank,
  ArrowRight,
  BookOpen,
  Flag,
  CaretRight,
  CheckCircle,
  Clock,
} from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE, backend } from "../api";
import { notices } from "../data";
import {
  StatCard,
  PanelTitle,
  Tabs,
  Badge,
  Modal,
  ErrorBox,
} from "../components";
export function Dashboard() {
  const { session, navigate, can } = useApp();
  const { data, update } = useStore();
  const [noticeTab, setNoticeTab] = useState("全部");
  const [taskTab, setTaskTab] = useState("全部");
  const [notice, setNotice] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    if (IS_LIVE) backend.health().catch(setError);
  }, []);
  const stats = IS_LIVE
    ? ["—", "—", "—", "—"]
    : [data.members.length.toLocaleString(), 68, 128, "96.5"];
  const tasks = data.tasks.filter(
    (t) =>
      taskTab === "全部" || (taskTab === "已完成" ? t.completed : !t.completed),
  );
  const quick = [
    {
      label: "党员管理",
      desc: "名册与档案",
      icon: UsersThree,
      route: "members",
      permission: "member.query",
      color: "red",
    },
    {
      label: "三会一课",
      desc: "会议与纪要",
      icon: CalendarBlank,
      route: "meetings",
      permission: "meeting.query",
      color: "orange",
    },
    {
      label: "学习教育",
      desc: "学习与成长",
      icon: BookOpen,
      route: "learning",
      permission: "study.query",
      color: "blue",
    },
    {
      label: "主题党日",
      desc: "活动与实践",
      icon: Flag,
      route: "activities",
      demo: true,
      color: "green",
    },
    {
      label: "党建工作库",
      desc: "制度与文件",
      icon: FileText,
      route: "knowledge",
      permission: "knowledge.query",
      color: "purple",
    },
    {
      label: "考核评价",
      desc: "指标与佐证",
      icon: ClipboardText,
      route: "assessment",
      permission: "assessment.query",
      color: "teal",
    },
  ];
  return (
    <div className="dashboard">
      <div className="dashboard-heading">
        <div>
          <h1>工作台</h1>
          <p>{session.user.name}，欢迎回来！让每一项党务工作有序推进。</p>
        </div>
        <span className="secure-status">
          <ShieldCheck weight="fill" size={16} />
          {IS_LIVE ? "业务数据模式" : "学校业务工作台"}
        </span>
      </div>
      {error && <ErrorBox error={error} />}
      <div className="dashboard-hero-row">
        <div className="campus-banner">
          <img
            src="/assets/campus-hero.png"
            alt="立校为党育人，为国育才。以高质量党建引领一流大学建设。"
          />
          <span className="banner-pagination">
            <i className="active" />
            <i />
            <i />
          </span>
        </div>
        <div className="assistant-card">
          <div className="assistant-card-heading">
            <Sparkle weight="fill" size={24} />
            <h2>党建智能体</h2>
          </div>
          <div className="assistant-intro">
            <img src="/assets/assistant-avatar.png" alt="党建智能助手" />
            <div>
              <h3>您好，我是高校党建智能体</h3>
              <p>
                您的贴心党务工作助手。
                <br />
                政策解读、材料写作，
                <br />
                让党务工作更高效。
              </p>
            </div>
          </div>
          <div className="assistant-shortcuts">
            {[
              {
                label: "政策咨询",
                icon: ShieldCheck,
                color: "purple",
                prompt: "我想了解党支部组织生活的制度要求",
              },
              {
                label: "材料写作",
                icon: PencilLine,
                color: "blue",
                prompt: "帮我起草一份主题党日活动方案",
              },
              {
                label: "工作建议",
                icon: ClipboardText,
                color: "red",
                prompt: "如何做好本月党支部工作安排",
              },
              {
                label: "数据分析",
                icon: ChartBar,
                color: "teal",
                prompt: "分析本月党支部活动参与情况",
              },
            ].map((x) => (
              <button
                key={x.label}
                className={x.color}
                onClick={() => navigate("assistant", { prompt: x.prompt })}
              >
                <x.icon weight="duotone" size={18} />
                {x.label}
                <CaretRight size={11} />
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="stats-grid">
        <StatCard
          icon={UsersThree}
          color="red"
          label="党员总数"
          value={stats[0]}
          unit="人"
          trend={IS_LIVE ? "" : "+12"}
        />
        <StatCard
          icon={TreeStructure}
          color="orange"
          label="党组织数量"
          value={stats[1]}
          unit="个"
          trend={IS_LIVE ? "" : "持平"}
        />
        <StatCard
          icon={GraduationCap}
          color="blue"
          label="本月活动"
          value={stats[2]}
          unit="次"
          trend={IS_LIVE ? "" : "+18%"}
        />
        <StatCard
          icon={ClipboardText}
          color="green"
          label="学习参与率"
          value={stats[3]}
          unit="%"
          trend={IS_LIVE ? "" : "+2.1%"}
        />
      </div>
      <div className="dashboard-middle">
        <section className="panel notices-panel">
          <PanelTitle
            title="通知公告"
            action="更多"
            onAction={() => setNotice({ title: "通知公告", list: true })}
          />
          <Tabs
            compact
            items={["全部", "学校文件", "组织部通知", "活动通知"]}
            active={noticeTab}
            onChange={setNoticeTab}
          />
          <div className="notice-list">
            {!IS_LIVE ? (
              notices
                .filter((n) => noticeTab === "全部" || n.type === noticeTab)
                .slice(0, 5)
                .map((n) => (
                  <button
                    className="notice-row"
                    key={n.id}
                    onClick={() => setNotice(n)}
                  >
                    <span className={`notice-tag category-${n.category}`}>
                      {n.category}
                    </span>
                    <span className="notice-text">{n.title}</span>
                    <time>{n.date}</time>
                  </button>
                ))
            ) : (
              <div className="subtle-empty">全校公告暂不可用，请联系学校管理员。</div>
            )}
          </div>
        </section>
        <section className="panel tasks-panel">
          <PanelTitle
            title="近期工作"
            action="查看全部"
            onAction={() => setTaskTab("全部")}
          />
          <Tabs
            compact
            items={["全部", "进行中", "已完成"]}
            active={taskTab}
            onChange={setTaskTab}
          />
          <div className="task-list">
            {tasks.map((t) => (
              <div
                className={`task-row ${t.completed ? "completed" : ""}`}
                key={t.id}
              >
                <input
                  type="checkbox"
                  checked={t.completed}
                  aria-label={`完成${t.title}`}
                  onChange={() =>
                    update("tasks", (prev) =>
                      prev.map((x) =>
                        x.id === t.id ? { ...x, completed: !x.completed } : x,
                      ),
                    )
                  }
                />
                <button onClick={() => navigate(t.route)}>{t.title}</button>
                <time>{t.date}</time>
                <Badge
                  tone={
                    t.completed
                      ? "green"
                      : t.status === "进行中"
                        ? "blue"
                        : "red"
                  }
                >
                  {t.completed ? "已完成" : t.status}
                </Badge>
              </div>
            ))}
            {tasks.length === 0 && (
              <div className="subtle-empty">暂无待办工作</div>
            )}
          </div>
          <div className="task-summary">
            <CheckCircle size={15} weight="duotone" />
            <span>
              已完成 {data.tasks.filter((t) => t.completed).length} 项工作
            </span>
            <span>积跬步，至千里</span>
          </div>
        </section>
      </div>
      <section className="panel quick-panel">
        <PanelTitle title="常用功能" />
        <div className="quick-grid">
          {quick
            .filter((q) => can({ ...q, id: q.route }))
            .map((q) => (
              <button
                key={q.route}
                className="quick-item"
                onClick={() => navigate(q.route)}
              >
                <div className={`quick-icon ${q.color}`}>
                  <q.icon size={25} weight="duotone" />
                </div>
                <div>
                  <h3>{q.label}</h3>
                  <p>{q.desc}</p>
                </div>
                <ArrowUpRight size={16} />
              </button>
            ))}
        </div>
      </section>
      <div className="dashboard-bottom">
        <section className="panel upcoming-panel">
          <PanelTitle
            title="本月活动"
            action="查看日历"
            onAction={() => navigate("meetings")}
          />
          <div className="upcoming-list">
            {data.meetings.slice(0, 2).map((m) => (
              <button
                key={m.id}
                onClick={() => navigate("meetings", { id: m.id })}
              >
                <div className="date-tile">
                  <b>{m.date.slice(8)}</b>
                  <small>{m.date.slice(5, 7)}月</small>
                </div>
                <div>
                  <h3>{m.title}</h3>
                  <p>
                    <Clock size={12} />
                    {m.time} <span>·</span> {m.location}
                  </p>
                </div>
                <Badge>{m.status}</Badge>
              </button>
            ))}
            {!data.meetings.length && (
              <div className="subtle-empty">暂无活动安排</div>
            )}
          </div>
        </section>
        <section className="panel learning-prompt">
          <div className="learning-prompt-icon">
            <BookOpen weight="duotone" size={35} />
          </div>
          <div>
            <h3>学思践悟，知行合一</h3>
            <p>每一天的学习，都让信仰更坚定。</p>
            <button
              className="text-button primary-text"
              onClick={() =>
                navigate(
                  can({ id: "learning", permission: "study.query" })
                    ? "learning"
                    : "assistant",
                )
              }
            >
              开始今日学习
              <ArrowRight size={15} />
            </button>
          </div>
        </section>
      </div>
      {notice && (
        <Modal title={notice.title} onClose={() => setNotice(null)} wide>
          {notice.list ? (
            <div className="all-notices">
              {notices.map((n) => (
                <button
                  className="notice-row"
                  key={n.id}
                  onClick={() => setNotice(n)}
                >
                  <span className="notice-text">{n.title}</span>
                  <time>{n.date}</time>
                </button>
              ))}
            </div>
          ) : (
            <>
              <div className="notice-meta">
                党委组织部 · 2026-{notice.date}{" "}
                <Badge tone="blue">通知公告</Badge>
              </div>
              <p className="body-copy">{notice.body}</p>
            </>
          )}
        </Modal>
      )}
    </div>
  );
}
