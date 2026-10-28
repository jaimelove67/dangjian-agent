import { useEffect, useRef, useState } from "react";
import {
  Sparkle,
  ShieldCheck,
  ChartBar,
  PencilLine,
  Briefcase,
  Question,
  ArrowUp,
  Plus,
  ClockCounterClockwise,
  PaperPlaneTilt,
  FileText,
  ArrowRight,
  MagnifyingGlass,
  Paperclip,
  X,
  CheckCircle,
  UsersThree,
  CalendarBlank,
  BookOpen,
  GraduationCap,
  DownloadSimple,
  GearSix,
  UploadSimple,
  CircleNotch,
  Chats,
  Quotes,
  Info,
  Lock,
  LinkSimple,
  Heart,
} from "@phosphor-icons/react";
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  AreaChart,
  Area,
} from "recharts";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE, backend, request } from "../api";
import { QA_QUESTION_MAX_LENGTH, questionText } from "../contracts";
import { scopedMembers, ROLE_INFO } from "../roles";
import { DEPARTMENTS, courses } from "../data";
import {
  PageHeader,
  PanelTitle,
  Tabs,
  SearchInput,
  Select,
  Badge,
  Modal,
  Field,
  Empty,
  ErrorBox,
  Loading,
  StatCard,
  exportCsv,
  downloadBlob,
} from "../components";
const services = [
  {
    title: "政策法规解读",
    description: "查制度、找依据，让工作有章可循",
    icon: ShieldCheck,
    color: "purple",
    prompt: "我想了解党支部组织生活的制度要求",
  },
  {
    title: "党务流程引导",
    description: "理清工作流程，把握关键节点",
    icon: FlagIcon,
    color: "red",
    prompt: "如何梳理发展党员的工作流程和材料清单？",
  },
  {
    title: "材料智能生成",
    description: "活动方案、会议提纲、工作总结",
    icon: PencilLine,
    color: "blue",
    prompt: "帮我起草一份“红色基因·青春力量”主题党日活动方案",
  },
  {
    title: "数据分析思路",
    description: "梳理分析口径与指标框架",
    icon: ChartBar,
    color: "teal",
    prompt: "如何分析本月党支部活动的参与情况？",
  },
  {
    title: "典型案例参考",
    description: "汲取先进经验，激发工作思路",
    icon: Briefcase,
    color: "orange",
    prompt: "为高校党支部志愿服务活动提供一些策划思路",
  },
  {
    title: "其他问题",
    description: "您的党务问题，随时为您解答",
    icon: Chats,
    color: "indigo",
    prompt: "如何安排本月的党支部工作？",
  },
];
function FlagIcon(props) {
  return <GraduationCap {...props} />;
}
const commonQuestions = [
  "如何开展主题党日活动？",
  "发展党员需要哪些材料？",
  "帮我起草一份三会一课记录模板",
  "分析本学期党员参与活动情况",
  "如何做好党员教育管理工作？",
];
function demoAnswer(q) {
  if (/方案|起草|模板|生成/.test(q))
    return {
      answer:
        "主题党日活动方案（讨论稿）\n\n一、活动主题\n红色基因·青春力量——在实践中传承，在行动中担当。\n\n二、活动目标\n结合支部实际，通过专题学习、实地研学与交流分享，增进党员理论学习与实践工作的联系。\n\n三、建议安排\n1. 行前准备：由组织人员核对活动主题、时间、地点和参与名单。\n2. 集中学习：选取已审核的学习材料，组织导读和交流。\n3. 实践研学：结合校史、红色文化或社区服务开展活动。\n4. 总结反馈：记录实际参与情况、形成交流纪要和后续行动清单。\n\n四、待补充事项\n请补充所属支部、活动日期、人员分工和实际预算，经支部讨论、人工审核后使用。",
      citations: [],
      disclaimer:
        "以上为工作模板，请补充实际情况，经组织人员审核后使用。",
    };
  return {
    answer:
      "我可以帮助您梳理这个问题的办理思路。\n\n1. 先明确工作对象、所属组织和希望完成的事项。\n2. 在“党建工作库”中查找学校现行制度与适用文件。\n3. 核对材料清单、办理条件和需要人工审核的环节。\n4. 由有权限的组织人员确认后，在相应工作台登记办理。\n\n当前未提供可核验的制度依据。以上为办理参考，请查阅学校现行制度，并由有权限的组织人员确认后办理。",
    citations: [],
    disclaimer:
      "办理参考 · 请以现行制度和组织审核意见为准。",
  };
}
export function Assistant() {
  const { routeParams, session } = useApp();
  const { data, update, notify } = useStore();
  const [input, setInput] = useState(routeParams.prompt || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState(false);
  const [citation, setCitation] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [started, setStarted] = useState(false);
  const [attachments, setAttachments] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [pendingOcr, setPendingOcr] = useState(null);
  const [conversationId, setConversationId] = useState(() =>
    crypto.randomUUID(),
  );
  const inputRef = useRef(null);
  const endRef = useRef(null);
  const fileRef = useRef(null);

  async function uploadAttachment(file, cloudOcr = false) {
    setUploading(true);
    setError(null);
    try {
      const res = await backend.uploadQaAttachment(file, cloudOcr);
      const item = res?.data || res || {};
      setAttachments((prev) => [
        ...prev,
        {
          id: item.id || item.attachment_id,
          file_name: item.file_name || file.name,
          chars: item.chars,
          truncated: item.truncated,
        },
      ]);
      notify(`已附加材料：${item.file_name || file.name}`);
    } catch (err) {
      setError(err);
    } finally {
      setUploading(false);
    }
  }

  function pickAttachment(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    // 图片与扫描件要送到云端识别，须先取得本人确认（涉密材料不出网）
    if (/\.(png|jpe?g|webp|bmp|tiff?)$/i.test(file.name)) {
      setPendingOcr(file);
      return;
    }
    uploadAttachment(file);
  }

  function removeAttachment(id) {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }
  const messages = started
    ? data.messages.filter(
        (m) =>
          m.conversationId === conversationId && m.owner_id === session.user.id,
      )
    : [];
  useEffect(() => {
    if (routeParams.prompt) setInput(routeParams.prompt);
  }, [routeParams.prompt]);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages.length, busy]);
  async function send(e) {
    e?.preventDefault();
    if (busy || uploading) return;
    if (!input.trim() && !attachments.length) return;
    let q = "";
    if (input.trim()) {
      try {
        q = questionText(input);
      } catch (err) {
        setError(err);
        return;
      }
    }
    setError(null);
    setBusy(true);
    setStarted(true);
    const id = crypto.randomUUID();
    const names = attachments.map((a) => a.file_name);
    update("messages", (prev) => [
      ...prev,
      {
        id,
        role: "user",
        owner_id: session.user.id,
        conversationId,
        content: q || "请结合我上传的材料作答。",
        attachments: names,
        createdAt: Date.now(),
      },
    ]);
    setInput("");
    try {
      const answer = IS_LIVE
        ? await backend.ask({
            question: q,
            ...(attachments.length
              ? { attachment_ids: attachments.map((a) => a.id) }
              : {}),
            ...(sessionId ? { session_id: sessionId } : {}),
          })
        : demoAnswer(q || "请结合我上传的材料作答。");
      setSessionId(answer.session_id || sessionId);
      // 附件只服务本次提问，回答生成后即摘除，不再随后续追问带出
      setAttachments([]);
      update("messages", (prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          owner_id: session.user.id,
          conversationId,
          sessionId: answer.session_id,
          content: answer.answer,
          citations: answer.citations || [],
          disclaimer: answer.disclaimer,
          refused: answer.refused,
          hasSufficientEvidence: answer.has_sufficient_evidence,
          warnings: answer.warnings || [],
          createdAt: Date.now(),
        },
      ]);
    } catch (err) {
      setError(err);
      setInput(q);
    } finally {
      setBusy(false);
    }
  }
  function choose(prompt) {
    setInput(prompt);
    inputRef.current?.focus();
  }
  function newConversation() {
    setConversationId(crypto.randomUUID());
    setStarted(false);
    setSessionId(null);
    setInput("");
    setAttachments([]);
    setError(null);
    notify("已新建会话");
  }
  return (
    <section className="panel assistant-workspace">
      <div className="ai-page-heading">
        <div className="ai-heading-brand">
          <Sparkle size={28} weight="fill" />
          <h1>党建智能体</h1>
          <span className="ai-heading-description">
            让党务工作更智能、更高效
          </span>
        </div>
        <button className="button secondary" onClick={() => setHistory(true)}>
          <ClockCounterClockwise size={17} />
          历史记录
        </button>
      </div>
      <div className={`ai-body ${messages.length ? "has-messages" : ""}`}>
        {!messages.length ? (
          <>
            <div className="ai-greeting">
              <img src="/assets/assistant-avatar.png" alt="您的党建智能助手" />
              <div>
                <h2>您好，有什么可以帮您？</h2>
                <p>从制度解读到材料起草，我会陪您把党务工作做细、做实。</p>
              </div>
            </div>
            <div className="ai-services-layout">
              <div className="ai-service-grid">
                {services.map((s) => (
                  <button
                    className="ai-service"
                    key={s.title}
                    onClick={() => choose(s.prompt)}
                  >
                    <div className={`service-icon ${s.color}`}>
                      <s.icon size={26} weight="duotone" />
                    </div>
                    <div>
                      <h3>{s.title}</h3>
                      <p>{s.description}</p>
                    </div>
                    <ArrowRight size={14} />
                  </button>
                ))}
              </div>
              <aside className="common-scenarios">
                <h3>常用场景</h3>
                {commonQuestions.map((q) => (
                  <button key={q} onClick={() => choose(q)}>
                    <span className="question-bullet" />
                    {q}
                    <ArrowRight size={12} />
                  </button>
                ))}
              </aside>
            </div>
            <div className="ai-empty-note">
              <ShieldCheck size={15} />
              制度类问题附引用；未检索到制度时提供办理参考
            </div>
          </>
        ) : (
          <div className="chat-messages">
            {messages.map((m) => (
              <div key={m.id} className={`message ${m.role}`}>
                <div className="message-avatar">
                  {m.role === "assistant" ? (
                    <Sparkle size={21} weight="fill" />
                  ) : (
                    "我"
                  )}
                </div>
                <div className="message-content">
                  <div className="message-label">
                    {m.role === "assistant" ? "党建智能体" : "您"}
                    {m.role === "assistant" && m.refused && (
                      <Badge tone="red">未找到依据</Badge>
                    )}
                    {m.role === "assistant" &&
                      !m.refused &&
                      !m.citations?.length && (
                        <Badge tone="orange">办理参考</Badge>
                      )}
                  </div>
                  <div className="message-text">{m.content}</div>
                  {m.attachments?.length > 0 && (
                    <div className="message-attachments">
                      {m.attachments.map((n, i) => (
                        <span key={`${n}-${i}`}>
                          <Paperclip size={11} />
                          {n}
                        </span>
                      ))}
                    </div>
                  )}
                  {m.citations?.length > 0 && (
                    <div className="citations">
                      {m.citations.map((c, i) => (
                        <button
                          key={c.doc_id || i}
                          onClick={() => setCitation(c)}
                        >
                          <FileText size={14} />[{c.index || i + 1}] {c.title}
                        </button>
                      ))}
                    </div>
                  )}
                  {m.disclaimer && (
                    <p className="message-disclaimer">{m.disclaimer}</p>
                  )}
                  {m.warnings?.map((w) => (
                    <p className="message-warning" key={w}>
                      {w}
                    </p>
                  ))}
                </div>
              </div>
            ))}
            {busy && (
              <div className="ai-typing">
                <CircleNotch className="spin" size={17} />
                正在检索并组织回答…
              </div>
            )}
            <div ref={endRef} />
          </div>
        )}
      </div>
      <div className="ai-composer-area">
        {error && <ErrorBox error={error} />}
        <form className="ai-composer" onSubmit={send}>
          {attachments.length > 0 && (
            <div className="qa-attachment-bar">
              {attachments.map((a) => (
                <span className="qa-attachment-chip" key={a.id}>
                  <Paperclip size={12} />
                  {a.file_name}
                  {a.truncated && <em>（正文已截断）</em>}
                  <button
                    type="button"
                    onClick={() => removeAttachment(a.id)}
                    aria-label={`移除材料 ${a.file_name}`}
                  >
                    <X size={11} />
                  </button>
                </span>
              ))}
            </div>
          )}
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                send();
              }
            }}
            rows={2}
            aria-label="向党建智能体提问"
            placeholder="请输入您的问题，例如：“帮我起草一份主题党日活动方案”"
          />
          <div className="ai-composer-bottom">
            <button
              type="button"
              className="qa-attach-button"
              onClick={() => fileRef.current?.click()}
              disabled={uploading || busy || !IS_LIVE}
              aria-label="上传附件"
              title={
                IS_LIVE
                  ? "附加本次提问要参考的材料（.txt/.md/.pdf/.docx；图片与扫描件须确认后送识别）"
                  : "当前为办理参考，暂不提供材料附加"
              }
            >
              {uploading ? (
                <CircleNotch className="spin" size={15} />
              ) : (
                <Paperclip size={15} />
              )}
              <span>{uploading ? "正在解析…" : "附件"}</span>
            </button>
            <span>最多 {QA_QUESTION_MAX_LENGTH} 字 · Enter 发送 · Shift + Enter 换行</span>
            <button
              className="send-button"
              disabled={
                (!input.trim() && !attachments.length) || busy || uploading
              }
              aria-label="发送问题"
            >
              <PaperPlaneTilt size={21} weight="fill" />
            </button>
          </div>
          <input
            ref={fileRef}
            type="file"
            hidden
            accept=".txt,.md,.pdf,.doc,.docx,.png,.jpg,.jpeg"
            onChange={pickAttachment}
          />
        </form>
        <div className="ai-footer">
          <button className="text-button muted" onClick={newConversation}>
            <Plus size={14} />
            新建会话
          </button>
          <span>
            {IS_LIVE
              ? "回答由授权知识库与模型辅助生成，请核对引用；未检索到制度时仅提供办理参考。"
              : "当前提供办理参考，请勿输入与问题无关的个人信息。"}
          </span>
        </div>
      </div>
      {history && (
        <Modal title="会话记录" wide flat onClose={() => setHistory(false)}>
          {data.messages
            .filter((m) => m.role === "user" && m.owner_id === session.user.id)
            .map((m) => (
              <button
                className="history-item"
                key={m.id}
                onClick={() => {
                  setConversationId(m.conversationId);
                  setSessionId(
                    data.messages
                      .filter(
                        (x) =>
                          x.conversationId === m.conversationId && x.sessionId,
                      )
                      .at(-1)?.sessionId || null,
                  );
                  setStarted(true);
                  setHistory(false);
                }}
              >
                <Chats size={19} />
                <span>
                  {m.content}
                  <small>{new Date(m.createdAt).toLocaleString("zh-CN")}</small>
                </span>
                <ArrowRight size={15} />
              </button>
            ))}
          {!data.messages.some(
            (m) => m.owner_id === session.user.id && m.role === "user",
          ) && (
            <Empty
              title="还没有会话记录"
              description="发送问题后，可在此查阅问答记录。"
            />
          )}
        </Modal>
      )}
      {pendingOcr && (
        <Modal
          title="图片材料识别确认"
          onClose={() => setPendingOcr(null)}
        >
          <p className="body-copy">
            材料「{pendingOcr.name}」为图片或扫描件，读取其中文字需发送至已授权的识别服务处理。
            涉密、敏感或未授权对外提供的材料请勿提交。
          </p>
          <div className="modal-actions">
            <button
              type="button"
              className="button secondary"
              onClick={() => setPendingOcr(null)}
            >
              取消
            </button>
            <button
              type="button"
              className="button primary"
              onClick={() => {
                const file = pendingOcr;
                setPendingOcr(null);
                uploadAttachment(file, true);
              }}
            >
              确认送识别
            </button>
          </div>
        </Modal>
      )}
      {citation && (
        <Modal title="引用来源" wide onClose={() => setCitation(null)}>
          <h3>{citation.title}</h3>
          <div className="notice-meta">
            {citation.issuer} · {citation.article || "原文摘录"}
          </div>
          <p className="body-copy">{citation.content}</p>
          {citation.content_revision && (
            <Badge>内容版本 {citation.content_revision}</Badge>
          )}
        </Modal>
      )}
    </section>
  );
}
const COLORS = ["#3774ff", "#f33545", "#1ab6a4", "#ffb237", "#8b6cf4"];
const chartData = [
  { name: "教职工党员", value: 412 },
  { name: "学生党员", value: 768 },
  { name: "管理人员", value: 106 },
];
const monthly = [
  { name: "5月", 学习活动: 35, 主题党日: 22 },
  { name: "6月", 学习活动: 48, 主题党日: 31 },
  { name: "7月", 学习活动: 42, 主题党日: 28 },
  { name: "8月", 学习活动: 28, 主题党日: 18 },
  { name: "9月", 学习活动: 66, 主题党日: 42 },
  { name: "10月", 学习活动: 78, 主题党日: 50 },
];
export function Analytics() {
  const { data } = useStore();
  const { session } = useApp();
  const visibleMembers = scopedMembers(data, session, IS_LIVE);
  const globalScope = ["all", "school"].includes(
    ROLE_INFO[session.user.role].scope,
  );
  const [tab, setTab] = useState("党员情况");
  const [scope, setScope] = useState(
    globalScope ? "全校" : session.user.department,
  );
  const [year, setYear] = useState("2026");
  const [degree, setDegree] = useState("学历");
  const scopedTotal =
    scope === "全校"
      ? visibleMembers.length
      : visibleMembers.filter((m) => m.department === scope).length;
  const factor = scopedTotal / 1286;
  const values = chartData.map((d, i) => ({
    ...d,
    value:
      i === 2
        ? Math.max(
            0,
            scopedTotal - Math.round(412 * factor) - Math.round(768 * factor),
          )
        : Math.round(d.value * factor),
  }));
  const ranking = (globalScope ? DEPARTMENTS : [session.user.department])
    .map((d) => ({
      name: d.replace("科学与技术", "").replace("学院", ""),
      value: visibleMembers.filter(
        (m) =>
          m.department === d && (scope === "全校" || m.department === scope),
      ).length,
    }))
    .filter((d) => d.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 5);
  return (
    <section className="panel workspace-panel analytics-page">
      <PageHeader
        title="数据分析"
        subtitle="用数据看见变化，以分析推动提升"
        action={
          <div className="inline-controls">
            <Select
              label="统计年度"
              value={year}
              onChange={(e) => setYear(e.target.value)}
            >
              <option>2026</option>
              <option>2025</option>
              <option>2024</option>
            </Select>
            <button
              className="button secondary"
              onClick={() =>
                exportCsv(
                  [
                    ["统计年度", "组织范围", "类别", "人数"],
                    ...values.map((v) => [
                      year,
                      scope,
                      v.name,
                      year === "2026" ? v.value : Math.round(v.value * 0.92),
                    ]),
                  ],
                  "党建数据.csv",
                )
              }
            >
              <DownloadSimple size={16} />
              导出数据
            </button>
          </div>
        }
      />
      <Tabs
        items={["党员情况", "学习情况", "活动参与", "考核评价"]}
        active={tab}
        onChange={setTab}
      />
      <div className="analytics-toolbar">
        <div className="segmented">
          {(globalScope
            ? ["全校", DEPARTMENTS[0], DEPARTMENTS[1]]
            : [session.user.department]
          ).map((s, i) => (
            <button
              key={s}
              className={scope === s ? "active" : ""}
              onClick={() => setScope(s)}
            >
              {i === 0 ? s : i === 1 ? "计算机学院" : "机械学院"}
            </button>
          ))}
        </div>
        <span className="muted small-text">{year}年度 · 统计概览</span>
      </div>
      {tab === "党员情况" ? (
        <>
          <div className="chart-grid">
            <div className="chart-panel">
              <PanelTitle title="党员类型分布" />
              <div className="donut-layout">
                <div className="donut-wrap">
                  <ResponsiveContainer width="100%" height={230}>
                    <PieChart>
                      <Pie
                        isAnimationActive={false}
                        data={values}
                        innerRadius={76}
                        outerRadius={101}
                        dataKey="value"
                        startAngle={90}
                        endAngle={-270}
                        stroke="none"
                        paddingAngle={2}
                      >
                        {values.map((v, i) => (
                          <Cell key={v.name} fill={COLORS[i]} />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="donut-center">
                    <strong>
                      {(year === "2026"
                        ? scopedTotal
                        : Math.round(scopedTotal * 0.92)
                      ).toLocaleString()}
                    </strong>
                    <span>党员总数 / 人</span>
                  </div>
                </div>
                <div className="chart-legend">
                  {values.map((v, i) => (
                    <div key={v.name}>
                      <i style={{ background: COLORS[i] }} />
                      <span>{v.name}</span>
                      <b>
                        {year === "2026" ? v.value : Math.round(v.value * 0.92)}
                      </b>
                      <small>
                        {scopedTotal
                          ? ((v.value / scopedTotal) * 100).toFixed(1)
                          : 0}
                        %
                      </small>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="chart-panel">
              <PanelTitle title="党员发展趋势" />
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart
                  data={[
                    { name: "2022", 人数: 980 },
                    { name: "2023", 人数: 1068 },
                    { name: "2024", 人数: 1126 },
                    { name: "2025", 人数: 1198 },
                    { name: "2026", 人数: scopedTotal },
                  ]}
                  margin={{ top: 20, right: 20, left: -15, bottom: 0 }}
                >
                  <CartesianGrid
                    strokeDasharray="3 4"
                    vertical={false}
                    stroke="#eceff4"
                  />
                  <XAxis
                    dataKey="name"
                    tickLine={false}
                    axisLine={false}
                    fontSize={11}
                  />
                  <YAxis tickLine={false} axisLine={false} fontSize={11} />
                  <Tooltip />
                  <Area
                    isAnimationActive={false}
                    type="monotone"
                    dataKey="人数"
                    stroke="#ed3541"
                    fill="#fff0f0"
                    strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>
          <div className="chart-grid">
            <div className="chart-panel">
              <PanelTitle title="党员性别结构" />
              <div className="gender-chart">
                {[
                  { label: "男党员", percent: 62.3, color: "blue" },
                  { label: "女党员", percent: 37.7, color: "red" },
                ].map((x) => (
                  <div key={x.label}>
                    <span className={`gender-label ${x.color}`}>{x.label}</span>
                    <div className="progress-track">
                      <div
                        className={x.color}
                        style={{ width: `${x.percent}%` }}
                      />
                    </div>
                    <b>{x.percent}%</b>
                  </div>
                ))}
              </div>
              <div className="education-head">
                <PanelTitle title="党员学历结构" />
                <div className="segmented">
                  <button
                    className={degree === "学历" ? "active" : ""}
                    onClick={() => setDegree("学历")}
                  >
                    学历
                  </button>
                  <button
                    className={degree === "年龄" ? "active" : ""}
                    onClick={() => setDegree("年龄")}
                  >
                    年龄
                  </button>
                </div>
              </div>
              <div className="education-chips">
                {(degree === "学历"
                  ? ["本科 56.2%", "硕士 28.6%", "博士 12.8%", "其他 2.4%"]
                  : [
                      "25岁以下 48.6%",
                      "26–35岁 24.2%",
                      "36–50岁 18.4%",
                      "50岁以上 8.8%",
                    ]
                ).map((s) => (
                  <span key={s}>{s}</span>
                ))}
              </div>
            </div>
            <div className="chart-panel">
              <PanelTitle title="党员学院分布（Top 5）" />
              <ResponsiveContainer width="100%" height={220}>
                <BarChart
                  data={ranking}
                  layout="vertical"
                  margin={{ left: 15, right: 35, top: 15 }}
                >
                  <XAxis type="number" hide />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={90}
                    tickLine={false}
                    axisLine={false}
                    fontSize={11}
                  />
                  <Tooltip />
                  <Bar
                    isAnimationActive={false}
                    dataKey="value"
                    fill="#76a0ff"
                    radius={[0, 3, 3, 0]}
                    barSize={17}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      ) : tab === "学习情况" || tab === "活动参与" ? (
        <div className="chart-panel large-chart">
          <PanelTitle
            title={tab === "学习情况" ? "月度学习与活动趋势" : "活动参与趋势"}
          />
          <ResponsiveContainer width="100%" height={370}>
            <BarChart
              data={monthly}
              margin={{ top: 30, right: 35, left: 5, bottom: 15 }}
            >
              <CartesianGrid vertical={false} strokeDasharray="3 4" />
              <XAxis dataKey="name" tickLine={false} axisLine={false} />
              <YAxis tickLine={false} axisLine={false} />
              <Tooltip />
              <Legend />
              <Bar
                isAnimationActive={false}
                dataKey="学习活动"
                fill="#427dff"
                radius={[4, 4, 0, 0]}
                barSize={25}
              />
              <Bar
                isAnimationActive={false}
                dataKey="主题党日"
                fill="#f13b49"
                radius={[4, 4, 0, 0]}
                barSize={25}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="chart-panel large-chart">
          <PanelTitle title="年度考核材料完成情况" />
          {[
            { label: "组织建设", value: 96 },
            { label: "党员教育", value: 92 },
            { label: "组织生活", value: 88 },
            { label: "作用发挥", value: 85 },
          ].map((x) => (
            <div className="assessment-progress" key={x.label}>
              <span>{x.label}</span>
              <div className="progress-track">
                <div className="red" style={{ width: x.value + "%" }} />
              </div>
              <b>{x.value}%</b>
            </div>
          ))}
        </div>
      )}
      <div className="page-note">
        统计结果用于工作分析，正式考核以经审核的业务记录与佐证材料为准。
      </div>
    </section>
  );
}
export function Profile() {
  const { session, navigate } = useApp();
  const { data } = useStore();
  const [archive, setArchive] = useState(null);
  const [error, setError] = useState(null);
  const [edit, setEdit] = useState(false);
  const student = session.user.role === "member";
  useEffect(() => {
    if (IS_LIVE && ["member", "applicant"].includes(session.user.role))
      backend.self().then(setArchive).catch(setError);
  }, [session.user.role]);
  const finished = Object.values(data.learning).filter(
    (l) => l.completed,
  ).length;
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title="个人中心"
        subtitle="记录每一步成长，让初心与使命同行"
        action={
          <span className="secure-status">
            <ShieldCheck size={16} />
            个人信息受保护
          </span>
        }
      />
      {error && <ErrorBox error={error} />}
      <div className="profile-layout">
        <aside className="profile-card">
          <img
            className="profile-portrait"
            src="/assets/profile-photo.png"
            alt="个人头像"
          />
          <h2>{session.user.name}</h2>
          <Badge tone="red">{student ? "学生党员" : "教师党员"}</Badge>
          <dl>
            <dt>工号 / 学号</dt>
            <dd>{session.user.username}</dd>
            <dt>所属单位</dt>
            <dd>
              {IS_LIVE
                ? archive?.profile?.org_name ||
                  archive?.org_name ||
                  "以账号归属为准"
                : "计算机科学与技术学院"}
            </dd>
            <dt>所属支部</dt>
            <dd>
              {IS_LIVE
                ? archive?.profile?.org_name || "以本人档案为准"
                : "教工第一党支部"}
            </dd>
            <dt>入党时间</dt>
            <dd>
              {IS_LIVE
                ? archive?.profile?.stage_joined_on || "未登记"
                : "2020-07-01"}
            </dd>
          </dl>
          <button
            className="button secondary profile-edit"
            onClick={() => setEdit(true)}
          >
            账号信息
          </button>
          <div className="profile-motto">不忘初心 · 牢记使命</div>
        </aside>
        <div className="profile-main">
          <PanelTitle title="我的党建数据" />
          <div className="profile-stats">
            <StatCard
              icon={ChartBar}
              color="blue"
              label="学习时长"
              value={IS_LIVE ? "—" : 36 + finished}
              unit="小时"
              note="累计学习"
            />
            <StatCard
              icon={CalendarBlank}
              color="orange"
              label="参与活动"
              value={IS_LIVE ? "—" : 12 + data.enrollments.length}
              unit="次"
              note="本学年累计"
            />
            <StatCard
              icon={GraduationCap}
              color="red"
              label="学习积分"
              value={IS_LIVE ? "—" : 256 + finished * 10}
              unit="分"
              note="持续学习，笃行不怠"
            />
            <StatCard
              icon={FlagIcon}
              color="red"
              label="主题党日"
              value={IS_LIVE ? "—" : 18}
              unit="小时"
              note="本学年累计"
            />
          </div>
          <section className="profile-section">
            <PanelTitle
              title="最近学习"
              action="全部学习"
              onAction={() => navigate("learning")}
            />
            {(!IS_LIVE ? courses.slice(0, 4) : []).map((c, i) => (
              <button
                className="profile-learning-row"
                key={c.id}
                onClick={() => navigate("learning")}
              >
                <span>
                  <BookOpen size={16} />
                  {c.title}
                </span>
                <time>2026-10-{22 - i * 2}</time>
                <Badge>
                  {data.learning[c.id]?.completed ? "已完成" : "学习中"}
                </Badge>
              </button>
            ))}
            {IS_LIVE && (
              <div className="subtle-empty">本人学习记录以授权业务模块为准</div>
            )}
          </section>
          <section className="profile-section">
            <PanelTitle title="我的待办" />
            {data.tasks.slice(0, 2).map((t) => (
              <button
                key={t.id}
                className="profile-learning-row"
                onClick={() => navigate(t.route)}
              >
                <span>
                  <CalendarBlank size={16} />
                  {t.title}
                </span>
                <time>{t.date} 截止</time>
                <Badge>{t.completed ? "已完成" : "待办理"}</Badge>
              </button>
            ))}
            {!data.tasks.length && <div className="subtle-empty">暂无待办</div>}
          </section>
        </div>
      </div>
      {edit && (
        <Modal title="账号信息" onClose={() => setEdit(false)}>
          <dl className="detail-list">
            <dt>显示姓名</dt>
            <dd>{session.user.name}</dd>
            <dt>登录账号</dt>
            <dd>{session.user.username}</dd>
            <dt>账号角色</dt>
            <dd>{session.user.role}</dd>
          </dl>
          <div className="inline-note">
            姓名、角色与组织归属由管理员核验维护。如需更正，请联系所在单位组织员。
          </div>
        </Modal>
      )}
    </section>
  );
}
export function Knowledge() {
  const { data, update, notify } = useStore();
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const [detail, setDetail] = useState(null);
  const [upload, setUpload] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function load() {
    if (!IS_LIVE) return;
    setBusy(true);
    try {
      const res = await backend.knowledge();
      update(
        "knowledge",
        (res.items || []).map((d) => ({
          ...d,
          date: d.effective_date || d.created_at?.slice(0, 10),
          type: d.level || "制度资料",
          level: d.visibility || "授权可见",
          status: d.status === "effective" ? "现行有效" : "待复核",
          summary: d.summary || "请在文件详情中查阅原文。",
        })),
      );
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    load();
  }, []);
  const filtered = data.knowledge.filter(
    (d) => d.title.includes(query) && (!type || d.type === type),
  );
  function add(e) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const file = f.get("file");
    if (!(file instanceof File) || !file.size) {
      setError(new Error("请选择有效文件"));
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      setError(new Error("文件大小不能超过20MB"));
      return;
    }
    update("knowledge", (prev) => [
      {
        id: crypto.randomUUID(),
        title: f.get("title").trim() || file.name,
        issuer: "本地登记",
        type: f.get("type"),
        date: "2026-10-23",
        status: "待复核",
        level: "校内",
        summary: `文件名：${file.name}。当前仅登记文件信息。请另行上传原件，完成入库审核后用于制度问答。`,
      },
      ...prev,
    ]);
    setUpload(false);
    notify("文件信息已登记，原件尚未上传");
  }
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title="党建工作库"
        subtitle="让制度有据可查，让工作有章可循"
        action={
          !IS_LIVE && (
            <button
              className="button primary"
              onClick={() => {
                setUpload(true);
                setError(null);
              }}
            >
              <UploadSimple size={17} />
              登记文件
            </button>
          )
        }
      />
      <Tabs items={["制度文件"]} active="制度文件" onChange={() => {}} />
      <div className="table-toolbar">
        <SearchInput
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索制度或文件名称"
        />
        <Select
          label="文件类型"
          value={type}
          onChange={(e) => setType(e.target.value)}
        >
          <option value="">全部分类</option>
          {[...new Set(data.knowledge.map((d) => d.type))].map((t) => (
            <option key={t}>{t}</option>
          ))}
        </Select>
      </div>
      {error && !upload && <ErrorBox error={error} retry={load} />}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>文件名称</th>
              <th>分类</th>
              <th>发布单位</th>
              <th>生效日期</th>
              <th>可见范围</th>
              <th>效力状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((d) => (
              <tr key={d.id}>
                <td>
                  <button className="file-name" onClick={() => setDetail(d)}>
                    <FileText weight="duotone" size={22} />
                    {d.title}
                  </button>
                </td>
                <td>{d.type}</td>
                <td>{d.issuer}</td>
                <td>{d.date}</td>
                <td>{d.level}</td>
                <td>
                  <Badge>{d.status}</Badge>
                </td>
                <td>
                  <button
                    className="text-button link"
                    onClick={() => setDetail(d)}
                  >
                    查看
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {busy && <Loading />}
        {!filtered.length && !busy && <Empty />}
      </div>
      <div className="page-note">
        正式制度以现行有效原文为准，知识库内容需审核后方可参与问答。
      </div>
      {detail && (
        <Modal title="文件信息" wide onClose={() => setDetail(null)}>
          <div className="document-heading">
            <FileText size={38} weight="duotone" />
            <div>
              <h3>{detail.title}</h3>
              <p>
                {detail.issuer} · {detail.date}
              </p>
            </div>
          </div>
          <div className="detail-meta">
            <Badge>{detail.status}</Badge>
            <Badge tone="blue">{detail.level}</Badge>
          </div>
          <p className="body-copy">{detail.summary}</p>
          <div className="inline-note">
            {IS_LIVE
              ? "当前展示资料基本信息，正文与引用以知识库收录内容为准。"
              : "当前仅有文件信息，尚未保存原件和解析正文。"}
          </div>
        </Modal>
      )}
      {upload && (
        <Modal title="登记制度文件" onClose={() => setUpload(false)}>
          <form onSubmit={add}>
            <div className="form-grid">
              <Field label="文件标题" full>
                <input
                  name="title"
                  maxLength={200}
                  placeholder="留空则使用文件名"
                />
              </Field>
              <Field label="分类" full>
                <select name="type">
                  {["党内法规", "党员发展", "组织建设", "学校制度"].map((t) => (
                    <option key={t}>{t}</option>
                  ))}
                </select>
              </Field>
              <Field label="选择文件（20MB以内）" required full>
                <input
                  name="file"
                  type="file"
                  accept=".pdf,.doc,.docx,.txt,.md"
                  required
                />
              </Field>
            </div>
            <div className="inline-note">
              此处仅登记文件信息；原件入库请在文件管理中办理。
            </div>
            {error && <ErrorBox error={error} />}
            <div className="modal-actions">
              <button
                type="button"
                className="button secondary"
                onClick={() => setUpload(false)}
              >
                取消
              </button>
              <button className="button primary">登记文件</button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}
const indicators = [
  {
    code: "A01",
    name: "基层组织建设",
    requirement: "完善组织设置与工作台账",
    progress: 96,
    target: 100,
  },
  {
    code: "A02",
    name: "党员教育管理",
    requirement: "落实年度党员教育安排",
    progress: 92,
    target: 100,
  },
  {
    code: "A03",
    name: "组织生活规范",
    requirement: "核对三会一课与活动记录",
    progress: 88,
    target: 100,
  },
  {
    code: "A04",
    name: "服务与作用发挥",
    requirement: "归集志愿服务与实践佐证",
    progress: 85,
    target: 100,
  },
  {
    code: "A05",
    name: "党风廉政建设",
    requirement: "汇总廉洁教育与提醒记录",
    progress: 90,
    target: 100,
  },
];
export function Assessment() {
  const { data, update, notify } = useStore();
  const [tab, setTab] = useState("年度指标");
  const [year, setYear] = useState("2026");
  const [workspace, setWorkspace] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [org, setOrg] = useState(null);
  const [detail, setDetail] = useState(null);
  async function load() {
    if (!IS_LIVE) return;
    setBusy(true);
    try {
      const orgs = await backend.assessmentOrgs();
      const first = org || orgs[0]?.id;
      if (!first) throw new Error("当前账号没有可用的考核组织。");
      setOrg(first);
      setWorkspace(await backend.assessment(first, Number(year)));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    load();
  }, [year]);
  const list = IS_LIVE
    ? (workspace?.results || []).map((i) => ({
        code: i.code,
        name: i.name,
        requirement: i.requirement,
        progress: i.actual ?? 0,
        target: i.target,
        unit: i.unit,
      }))
    : indicators;
  async function calculate() {
    if (!IS_LIVE) {
      notify("指标核对记录已保存，材料归集与审核请按学校工作要求办理。");
      return;
    }
    setBusy(true);
    try {
      await request("/assessment/recalculate", {
        method: "POST",
        body: JSON.stringify({ org_unit_id: org, year: Number(year) }),
      });
      await load();
      notify("材料已归集，请提交人工审核");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function exportData() {
    if (!IS_LIVE) {
      exportCsv(
        [
          ["年度", "指标", "要求", "登记完成值", "目标"],
          ...list.map((i) => [
            year,
            i.name,
            i.requirement,
            i.progress,
            i.target,
          ]),
        ],
        "考核指标.csv",
      );
      return;
    }
    const approved = workspace?.runs?.find(
      (r) => r.review_status === "approved",
    );
    if (!approved) {
      notify("尚无人工审核通过的归集版本，暂不能导出", "error");
      return;
    }
    try {
      downloadBlob(
        await request(
          `/assessment/runs/${encodeURIComponent(approved.id)}/export`,
          { method: "POST", download: true },
        ),
        "考核材料目录.zip",
      );
    } catch (e) {
      setError(e);
    }
  }
  return (
    <section className="panel workspace-panel">
      <PageHeader
        title="考核评价"
        subtitle="以评促建，以评促改，推动党建工作提质增效"
        action={
          <div className="inline-controls">
            <Select
              label="考核年度"
              value={year}
              onChange={(e) => setYear(e.target.value)}
            >
              <option>2026</option>
              <option>2025</option>
            </Select>
            <button className="button secondary" onClick={exportData}>
              <DownloadSimple size={17} />
              导出目录
            </button>
            <button
              className="button primary"
              onClick={calculate}
              disabled={busy}
            >
              归集材料
            </button>
          </div>
        }
      />
      <Tabs
        items={["年度指标", "任务管理", "佐证材料"]}
        active={tab}
        onChange={setTab}
      />
      {error && <ErrorBox error={error} retry={load} />}
      <div className="assessment-stats">
        <div>
          <p>年度考核指标</p>
          <strong>
            {list.length}
            <small>项</small>
          </strong>
        </div>
        <div>
          <p>已归集材料</p>
          <strong>
            {IS_LIVE ? workspace?.evidence?.length || 0 : 28}
            <small>份</small>
          </strong>
        </div>
        <div>
          <p>待人工审核</p>
          <strong>
            {IS_LIVE
              ? workspace?.runs?.filter((r) => r.review_status === "pending")
                  .length || 0
              : 3}
            <small>项</small>
          </strong>
        </div>
        <div>
          <p>考核年度</p>
          <strong>{year}</strong>
        </div>
      </div>
      {tab === "年度指标" ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>指标编号</th>
                <th>指标名称</th>
                <th>工作要求</th>
                <th>完成情况</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {list.map((i) => (
                <tr key={i.code}>
                  <td>{i.code}</td>
                  <td>{i.name}</td>
                  <td>{i.requirement}</td>
                  <td>
                    <div className="inline-progress">
                      <div className="progress-track">
                        <div
                          className="red"
                          style={{
                            width:
                              Math.min(
                                100,
                                Math.max(
                                  0,
                                  (i.progress / (i.target || 1)) * 100,
                                ),
                              ) + "%",
                          }}
                        />
                      </div>
                      <span>
                        {i.progress}
                        {i.unit || "%"}
                      </span>
                    </div>
                  </td>
                  <td>
                    <Badge tone="orange">待人工核验</Badge>
                  </td>
                  <td>
                    <button
                      className="text-button link"
                      onClick={() => setDetail(i)}
                    >
                      查看佐证
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {busy && <Loading />}
        </div>
      ) : tab === "任务管理" ? (
        <div className="assessment-task-list">
          {(IS_LIVE ? workspace?.tasks || [] : data.tasks).map((t) => (
            <div className="learning-plan" key={t.id}>
              <ClipboardTextIcon />
              <div>
                <h3>{t.title}</h3>
                <p>截止日期：{t.date || t.due_date}</p>
              </div>
              <Badge>
                {t.completed ? "已完成" : t.review_status || "待办理"}
              </Badge>
              {!IS_LIVE && (
                <button
                  className="button secondary"
                  onClick={() => {
                    update("tasks", (prev) =>
                      prev.map((x) =>
                        x.id === t.id ? { ...x, completed: !x.completed } : x,
                      ),
                    );
                    notify("任务状态已更新");
                  }}
                >
                  {t.completed ? "重新办理" : "标记完成"}
                </button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="evidence-list">
          {(IS_LIVE ? workspace?.evidence || [] : data.knowledge).map((d) => (
            <div className="learning-plan" key={d.id}>
              <FileText size={23} />
              <div>
                <h3>{d.title || d.requirement_key}</h3>
                <p>版本核对 · 材料佐证</p>
              </div>
              <Badge tone="orange">{d.review_status || "待核验"}</Badge>
            </div>
          ))}
        </div>
      )}
      <div className="page-note">
        考核结果须由有权限的组织人员人工确认，系统不自动形成组织评价。
      </div>
      {detail && (
        <Modal title="指标与佐证" onClose={() => setDetail(null)}>
          <h3>{detail.name}</h3>
          <p className="body-copy">{detail.requirement}</p>
          <div className="inline-note">
            请核对原始业务记录、材料版本与适用年度，并在相关业务档案中补齐佐证原件。
          </div>
        </Modal>
      )}
    </section>
  );
}
function ClipboardTextIcon() {
  return <FileText size={24} weight="duotone" />;
}
export function Settings() {
  const { session } = useApp();
  const { notify } = useStore();
  const [tab, setTab] = useState("基本设置");
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function check() {
    setBusy(true);
    setError(null);
    try {
      if (!IS_LIVE) {
        setStatus({ status: "demo" });
        return;
      }
      setStatus(await backend.health());
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel workspace-panel">
      <PageHeader title="系统管理" subtitle="明确权限边界，保障业务有序运行" />
      <Tabs
        items={["基本设置", "角色与权限", "接入状态"]}
        active={tab}
        onChange={setTab}
      />
      {tab === "基本设置" ? (
        <div className="settings-content">
          <PanelTitle title="平台信息" />
          <dl className="settings-list">
            <dt>平台名称</dt>
            <dd>高校智慧党建平台</dd>
            <dt>当前账号</dt>
            <dd>
              {session.user.name} · {session.user.username}
            </dd>
            <dt>运行环境</dt>
            <dd>
              <Badge tone={IS_LIVE ? "green" : "orange"}>
                {IS_LIVE ? "在线业务服务" : "本地工作区"}
              </Badge>
            </dd>
            <dt>数据来源</dt>
            <dd>{IS_LIVE ? "授权业务服务" : "当前工作区记录"}</dd>
          </dl>
          <div className="inline-note">
            <ShieldCheck size={18} />
            账号、角色与组织归属由管理员维护，可办理事项以当前账号授权范围为准。
          </div>
        </div>
      ) : tab === "角色与权限" ? (
        <div className="settings-content">
          <PanelTitle title="角色范围" />
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>角色</th>
                  <th>主要范围</th>
                  <th>业务边界</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>平台管理员</td>
                  <td>账号、租户、运行与审计</td>
                  <td>账号与租户登记仅平台角色可进入</td>
                </tr>
                <tr>
                  <td>校级管理员</td>
                  <td>全校组织、党员、审核与考核</td>
                  <td>按学校租户授权，不提供平台开户入口</td>
                </tr>
                <tr>
                  <td>院系管理员</td>
                  <td>授权范围内党员、组织生活与考核</td>
                  <td>仅所属院系</td>
                </tr>
                <tr>
                  <td>支部书记</td>
                  <td>支部工作登记与材料核对</td>
                  <td>审核按当前账号授权范围办理</td>
                </tr>
                <tr>
                  <td>组织员</td>
                  <td>支部材料接收、培养登记与纪要维护</td>
                  <td>仅所属支部，纪要不能自审</td>
                </tr>
                <tr>
                  <td>党员 / 申请人</td>
                  <td>本人档案、个人材料、制度问答</td>
                  <td>仅本人范围</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="settings-content">
          <PanelTitle title="服务接入" />
          <div className="integration-card">
            <div className="stat-icon green">
              <LinkSimple size={28} />
            </div>
            <div>
              <h3>党建业务服务</h3>
              <p>
                {IS_LIVE
                  ? "已配置业务服务连接"
                  : "业务服务尚未连接，当前仅可查看本地工作区记录。"}
              </p>
            </div>
            <button
              className="button secondary"
              disabled={busy}
              onClick={check}
            >
              {busy ? "检查中…" : "检查状态"}
            </button>
          </div>
          {error && <ErrorBox error={error} />}{" "}
          {status && (
            <div className="success-note">
              <CheckCircle size={18} />
              {status.status === "demo"
                ? "本地工作区运行正常，业务服务尚未连接。"
                : status.status === "ready"
                  ? "业务服务已就绪"
                  : "服务状态：" + status.status}
            </div>
          )}
          <div className="inline-note">
            如需调整服务连接及运行配置，请联系平台管理员。
          </div>
        </div>
      )}
    </section>
  );
}
