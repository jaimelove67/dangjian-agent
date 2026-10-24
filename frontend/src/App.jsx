import { useState, useEffect, lazy, Suspense } from "react";
import { AppContext, useApp } from "./app-context";
import { Icon } from "@iconify/react";
import hammerSickle from "@iconify-icons/mdi/hammer-sickle";
import {
  House,
  Sparkle,
  TreeStructure,
  UsersThree,
  CalendarBlank,
  Flag,
  BookOpen,
  GraduationCap,
  IdentificationCard,
  Books,
  ChartBar,
  ClipboardText,
  GearSix,
  Pulse,
  SlidersHorizontal,
  Bell,
  SquaresFour,
  CaretDown,
  CaretRight,
  List,
  SignOut,
  Key,
  UserCircle,
  MagnifyingGlass,
  ShieldCheck,
  X,
} from "@phosphor-icons/react";
import { StoreProvider, useStore } from "./store";
import { IS_LIVE, backend, getSession, saveSession, clearSession } from "./api";
import {
  Modal,
  ErrorBox,
  Field,
  Badge,
  Empty,
  PageHeader,
  Loading,
} from "./components";
import { Dashboard } from "./pages/Dashboard";
import { RoleHome } from "./pages/RoleHome";
import { AccountSettings } from "./pages/AccountSettings";
import { PasswordDialog } from "./components/PasswordSecurity";
import {
  canChangeOwnPassword,
  demoPasswordService,
  subscribePasswordSecurity,
} from "./password-security";
import {
  SchoolDashboard,
  SchoolRecordsPage,
  SchoolDevelopment,
  SchoolStatistics,
  SchoolNotices,
  SchoolManagement,
} from "./pages/SchoolWorkspace";
import {
  SCHOOL_NAVIGATION,
  schoolNavigationGroup,
  schoolRouteLabel,
} from "./school-navigation";
const PlatformHome = lazy(() =>
  import("./pages/PlatformHome").then((m) => ({ default: m.PlatformHome })),
);
const PlatformOperations = lazy(() =>
  import("./pages/PlatformOperations").then((m) => ({
    default: m.PlatformOperations,
  })),
);
const PlatformConfiguration = lazy(() =>
  import("./pages/PlatformOperations").then((m) => ({
    default: m.PlatformConfiguration,
  })),
);
const PlatformTenants = lazy(() =>
  import("./pages/PlatformIdentity").then((m) => ({
    default: m.PlatformTenants,
  })),
);
const PlatformAccounts = lazy(() =>
  import("./pages/PlatformIdentity").then((m) => ({
    default: m.PlatformAccounts,
  })),
);
const PlatformAudit = lazy(() =>
  import("./pages/PlatformIdentity").then((m) => ({
    default: m.PlatformAudit,
  })),
);
import { PersonalHome, OwnArchive, OwnMaterials } from "./pages/Personal";
import {
  MaterialInbox,
  ReviewCenter,
  DevelopmentWorkbench,
} from "./pages/RoleManagement";
import { Administration } from "./pages/Administration";
import {
  DEMO_PERSONAS,
  ROLE_INFO,
  demoSession,
  normalizeDemoSession,
  sessionForAccount,
  roleLabel,
  canAccess,
  isSelfService,
  hasPermission,
  scopeLabel,
  scopedMembers,
  PLATFORM_NAV_SPEC,
  demoAccountAvailable,
} from "./roles";
import { Organization, Members } from "./pages/Members";
import { Meetings, Activities, Learning } from "./pages/Activities";
import {
  Assistant,
  Analytics,
  Profile,
  Knowledge,
  Assessment,
  Settings,
} from "./pages/Workspace";
const LiveAssessment = lazy(() => import("./pages/LiveAssessment").then(m => ({ default: m.LiveAssessment })));
const LiveLearning = lazy(() => import("./pages/LiveLearningWorkspace").then(m => ({ default: m.LiveLearningWorkspace })));
const LivePersonalWorkspace = lazy(() => import("./pages/LiveLearningWorkspace").then(m => ({ default: m.LivePersonalWorkspace })));
const LiveSchoolBusiness = lazy(() => import("./pages/LiveSchoolBusiness").then(m => ({ default: m.LiveSchoolBusiness })));
const LiveEducation = lazy(() => import("./pages/LiveEducation").then(m => ({ default: m.LiveEducation })));
const LiveKnowledge = lazy(() => import("./pages/LiveKnowledge").then(m => ({ default: m.LiveKnowledge })));
const LiveBusinessWorkspace = lazy(() => import("./pages/LiveBusinessWorkspace").then(m => ({ default: m.LiveBusinessWorkspace })));
export const NAV = [
  {
    id: "operations",
    label: "系统运维",
    icon: Pulse,
    permission: "admin.ops",
    roles: ["system_admin"],
  },
  {
    id: "configuration",
    label: "平台配置",
    icon: SlidersHorizontal,
    permission: "admin.config",
    roles: ["system_admin"],
  },
  { id: "dashboard", label: "首页", icon: House, section: "工作空间" },
  {
    id: "school-supervision",
    label: "问题与督办",
    icon: Bell,
    permission: "admin.review",
    roles: ["school_admin"],
  },
  {
    id: "school-development",
    label: "全校发展进度",
    icon: GraduationCap,
    permission: "member.query",
    roles: ["school_admin"],
  },
  {
    id: "school-life",
    label: "开展检查与归档",
    icon: CalendarBlank,
    permission: "meeting.query",
    roles: ["school_admin"],
  },
  {
    id: "school-learning",
    label: "全校学习计划与任务",
    icon: BookOpen,
    permission: "study.query",
    roles: ["school_admin"],
  },
  {
    id: "school-notices",
    label: "通知公告",
    icon: Bell,
    permission: "study.query",
    roles: ["school_admin"],
  },
  {
    id: "school-accounts",
    label: "本校账号管理",
    icon: UsersThree,
    permission: "admin.identity",
    roles: ["school_admin"],
  },
  {
    id: "school-permissions",
    label: "业务权限申请",
    icon: ShieldCheck,
    permission: "admin.config",
    roles: ["school_admin"],
  },
  {
    id: "school-rules",
    label: "学校业务参数",
    icon: GearSix,
    permission: "admin.config",
    roles: ["school_admin"],
  },
  {
    id: "assistant",
    label: "党建智能体",
    icon: Sparkle,
    badge: "AI",
    permission: "qa.ask",
  },
  {
    id: "self-archive",
    label: "本人档案",
    icon: IdentificationCard,
    section: "本人服务",
    permission: "member.self_query",
    roles: ["member", "applicant"],
  },
  {
    id: "self-materials",
    label: "个人材料",
    icon: FileTextIcon,
    permission: "member.material_submit",
    roles: ["member", "applicant"],
  },
  {
    id: "reviews",
    label: "审核工作台",
    icon: ClipboardText,
    section: "工作办理",
    permission: "admin.review",
  },
  { id: "inbox", label: "材料接收", icon: Books, permission: "member.query" },
  {
    id: "organization",
    label: "组织建设",
    icon: TreeStructure,
    section: "党务管理",
    permission: "member.query",
  },
  {
    id: "members",
    label: "党员管理",
    icon: UsersThree,
    permission: "member.query",
  },
  {
    id: "meetings",
    label: "三会一课",
    icon: CalendarBlank,
    permission: "meeting.query",
  },
  { id: "activities", label: "主题党日", icon: Flag, permission: "meeting.query" },
  {
    id: "learning",
    label: "学习教育",
    icon: BookOpen,
    section: "学习与发展",
    permission: "study.query",
  },
  {
    id: "development",
    label: "发展党员",
    icon: GraduationCap,
    permission: "member.query",
  },
  {
    id: "archive",
    label: "党员档案",
    icon: IdentificationCard,
    permission: "member.query",
  },
  {
    id: "knowledge",
    label: "党建工作库",
    icon: Books,
    permission: "knowledge.query",
  },
  {
    id: "analytics",
    label: "数据分析",
    icon: ChartBar,
    section: "统计与服务",
    demo: true,
  },
  {
    id: "assessment",
    label: "考核评价",
    icon: ClipboardText,
    permission: "assessment.query",
  },
  { id: "profile", label: "个人中心", icon: UserCircle, avatarOnly: true },
  {
    id: "accounts",
    label: "账号管理",
    icon: UsersThree,
    section: "平台管理",
    permission: "admin.identity",
    roles: ["system_admin"],
  },
  {
    id: "tenants",
    label: "租户管理",
    icon: BuildingsIcon,
    permission: "admin.identity",
    roles: ["system_admin"],
  },
  {
    id: "audit",
    label: "审计日志",
    icon: ShieldCheck,
    permission: "admin.audit",
  },
  {
    id: "settings",
    label: "系统管理",
    icon: GearSix,
    permission: "admin.config",
    roles: ["system_admin"],
  },
];
export const PLATFORM_NAV = PLATFORM_NAV_SPEC.map((item, i) => ({
  ...NAV.find((n) => n.id === item.id),
  ...item,
  section: i === 0 ? "平台管理" : undefined,
  roles: ["system_admin"],
}));
function navForUser(user) {
  return user?.role === "system_admin" ? PLATFORM_NAV : NAV;
}
function FileTextIcon(props) {
  return <Books {...props} />;
}
function BuildingsIcon(props) {
  return <TreeStructure {...props} />;
}
export function Brand({ large = false, name = "高校智慧党建平台" }) {
  return (
    <div className={`brand ${large ? "large" : ""}`}>
      <Icon icon={hammerSickle} width={large ? 68 : 31} />
      <div>
        <strong>{name}</strong>
        {large && <p>立德树人 · 党建引领</p>}
      </div>
    </div>
  );
}
function Login() {
  const { setSession, navigate } = useApp();
  const { data } = useStore();
  const [mode, setMode] = useState("账号登录");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [help, setHelp] = useState(false);
  async function submit(e) {
    e.preventDefault();
    setError(null);
    const form = new FormData(e.currentTarget);
    setBusy(true);
    try {
      const username = form.get("username").trim(),
        password = form.get("password");
      const account = !IS_LIVE
        ? data.accounts.find(
            (a) =>
              a.username === username && demoAccountAvailable(a, data.tenants),
          )
        : null;
      const verified =
        !IS_LIVE && account
          ? await demoPasswordService().verify(account, password)
          : null;
      if (!IS_LIVE && !verified?.valid)
        throw new Error(
          "账号或密码不正确，请核对后重新登录。",
        );
      const s = IS_LIVE
        ? await backend.login(username, password)
        : sessionForAccount(account, verified.version);
      saveSession(s);
      setSession(s);
      navigate("dashboard");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-screen">
      <div className="login-identity">
        <Brand large name={data.platform?.config?.general?.platform_name} />
        <div className="login-tagline">以高质量党建引领高等教育高质量发展</div>
      </div>
      <div className="login-card">
        <div className="login-tabs">
          {["账号登录", "扫码登录"].map((t) => (
            <button
              key={t}
              className={mode === t ? "active" : ""}
              onClick={() => setMode(t)}
            >
              {t}
            </button>
          ))}
        </div>
        {mode === "账号登录" ? (
          <form onSubmit={submit}>
            {!IS_LIVE && (
              <Field label="选择登录身份">
                <select
                  aria-label="选择登录身份"
                  onChange={(e) => {
                    const input = e.currentTarget.form.elements.username;
                    Object.getOwnPropertyDescriptor(
                      HTMLInputElement.prototype,
                      "value",
                    ).set.call(input, e.target.value);
                    input.dispatchEvent(new Event("input", { bubbles: true }));
                  }}
                  defaultValue="admin"
                >
                  {DEMO_PERSONAS.map((p) => (
                    <option value={p.user.username} key={p.id}>
                      {p.title} · {p.user.username}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Field label="账号">
              <input
                name="username"
                placeholder="请输入工号 / 学号 / 账号"
                autoComplete="username"
                defaultValue={IS_LIVE ? "" : "admin"}
                required
              />
            </Field>
            <Field label="密码">
              <input
                name="password"
                type="password"
                placeholder="请输入密码"
                autoComplete="current-password"
                defaultValue={IS_LIVE ? "" : "123456"}
                required
              />
            </Field>
            <div className="login-options">
              <span>账号认证 · 会话登录</span>
              <button
                type="button"
                className="text-button muted"
                onClick={() => setHelp(true)}
              >
                忘记密码？
              </button>
            </div>
            {error && <ErrorBox error={error} />}
            <button className="button primary login-submit" disabled={busy}>
              {busy ? "正在登录…" : "登录"}
            </button>
          </form>
        ) : (
          <div className="scan-unavailable">
            <ShieldCheck size={45} weight="duotone" />
            <h3>统一身份认证</h3>
            <p>
              扫码认证服务暂不可用。
              <br />
              请使用账号密码登录。
            </p>
            <button
              className="button secondary"
              onClick={() => setMode("账号登录")}
            >
              使用账号登录
            </button>
          </div>
        )}
      </div>
      <div className="login-footer">
        高校智慧党建平台 · 让党务工作更智能、更高效
      </div>
      {help && (
        <Modal title="找回账号与密码" onClose={() => setHelp(false)}>
          <p className="body-copy">
            请联系学校管理员或平台管理员核验身份后重置密码。
          </p>
        </Modal>
      )}
    </div>
  );
}
function Shell() {
  const { route, routeParams, navigate, session, setSession, can } = useApp();
  const { data, update, notify, storageFailed } = useStore();
  const [mobileNav, setMobileNav] = useState(false);
  const [search, setSearch] = useState("");
  const [showSearch, setShowSearch] = useState(false);
  const [notification, setNotification] = useState(false);
  const [rolePicker, setRolePicker] = useState(false);
  const [passwordDialog, setPasswordDialog] = useState(false);
  const school = session.user.role === "school_admin";
  const selfService = isSelfService(session.user);
  const schoolGroup = schoolNavigationGroup(route);
  const [expandedGroup, setExpandedGroup] = useState(
    schoolGroup?.id || "school-home",
  );
  const schoolIcons = {
    House,
    TreeStructure,
    GraduationCap,
    CalendarBlank,
    BookOpen,
    ChartBar,
    GearSix,
  };
  const navItems = navForUser(session.user).filter(
    (item) => !item.avatarOnly && can(item),
  );
  const selected =
    navForUser(session.user).find((n) => n.id === route) ||
    NAV.find((n) => n.id === route) ||
    NAV.find((n) => n.id === "dashboard");
  useEffect(() => {
    setMobileNav(false);
    if (schoolGroup) setExpandedGroup(schoolGroup.id);
  }, [route]);
  async function logout() {
    try {
      if (IS_LIVE) await backend.logout();
      clearSession();
      setSession(null);
      navigate("login");
    } catch (error) {
      notify(error.message, "error");
    }
  }
  function switchRole(id) {
    const preset = DEMO_PERSONAS.find((p) => p.id === id);
    const account = data.accounts.find((a) => a.id === preset.user.id);
    if (!demoAccountAvailable(account, data.tenants)) {
      notify("该账号或所属学校已停用，请联系管理员。", "error");
      return;
    }
    const s = sessionForAccount(
      account,
      demoPasswordService().revision(account),
    );
    saveSession(s);
    setSession(s);
    setRolePicker(false);
    navigate("dashboard");
  }
  function globalSearch(e) {
    e.preventDefault();
    if (search.trim()) setShowSearch(true);
  }
  const results = navItems.filter((n) => n.label.includes(search.trim()));
  const memberResults = can(NAV.find((n) => n.id === "members"))
    ? scopedMembers(data, session, IS_LIVE)
        .filter((m) => m.name.includes(search.trim()))
        .slice(0, 4)
    : [];
  const visibleTasks =
    session.user.role === "system_admin"
      ? [
          ...(data.platform?.incidents || [])
            .filter((i) => i.status === "open")
            .map((i) => ({
              id: i.id,
              title: i.message,
              date: i.last_seen?.slice(0, 10),
              route: "operations",
              completed: false,
            })),
          ...(data.platform?.jobs || [])
            .filter((j) => j.status === "failed")
            .map((j) => ({
              id: j.id,
              title: j.name + " · 处理失败",
              date: j.created_at?.slice(0, 10),
              route: "operations",
              completed: false,
            })),
        ]
      : ["school_admin"].includes(session.user.role)
        ? data.tasks.filter(
            (t) =>
              (t.tenant_id || "school-1") === session.user.tenant_id &&
              can(NAV.find((n) => n.id === t.route)),
          )
        : [];
  return (
    <div className={`app-shell${school ? " school-shell" : ""}`}>
      <header className="topbar">
        <button
          className="icon-button mobile-menu"
          aria-label="展开导航"
          onClick={() => setMobileNav((v) => !v)}
        >
          <List size={24} />
        </button>
        <button
          className="brand-button"
          onClick={() => navigate("dashboard")}
          aria-label="高校智慧党建平台首页"
        >
          <Brand name={data.platform?.config?.general?.platform_name} />
        </button>
        <div className="topbar-right">
          <form className="global-search" onSubmit={globalSearch}>
            <MagnifyingGlass size={16} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={
                session.user.role === "system_admin"
                  ? "搜索平台管理功能…"
                  : "搜索党员、组织、活动、文件…"
              }
              aria-label="全局搜索"
            />
            <kbd>↵</kbd>
          </form>
          <span className="environment-tag">
            {IS_LIVE ? "业务环境" : "本地工作区"}
          </span>
          {!IS_LIVE && (
            <button
              className="role-switch-button"
              onClick={() => setRolePicker(true)}
            >
              <UsersThree size={16} />
              切换角色
            </button>
          )}
          <div className="notification-wrap">
            <button
              className="icon-button top-icon"
              aria-label="消息通知"
              onClick={() => {
                setNotification((v) => !v);
                update("notificationRead", true);
              }}
            >
              <Bell size={21} />
              {!data.notificationRead && <i />}
            </button>
            {notification && (
              <div className="notification-popover">
                <strong>工作提醒</strong>
                {visibleTasks
                  .filter((t) => !t.completed)
                  .map((t) => (
                    <button
                      key={t.id}
                      onClick={() => {
                        navigate(t.route);
                        setNotification(false);
                      }}
                    >
                      <span>{t.title}</span>
                      <small>
                        {t.date} 截止
                        <CaretRight size={11} />
                      </small>
                    </button>
                  ))}
                {visibleTasks.every((t) => t.completed) && <p>暂无待办提醒</p>}
              </div>
            )}
          </div>
          <button
            className="icon-button top-icon app-grid"
            aria-label="应用导航"
            onClick={() => setMobileNav((v) => !v)}
          >
            <SquaresFour size={21} weight="fill" />
          </button>
          <details className="user-menu">
            <summary>
              <img src="/assets/profile-photo.png" alt="用户头像" />
              <span>
                <b>{session.user.name}</b>
                <small>{roleLabel(session.user)}</small>
              </span>
              <CaretDown size={12} />
            </summary>
            <div className="user-dropdown">
              <button
                onClick={(e) => {
                  navigate(selfService ? "self-archive" : "profile");
                  e.currentTarget.closest("details").open = false;
                }}
              >
                <UserCircle size={17} />
                {selfService ? "个人档案" : "个人中心"}
              </button>
              {canChangeOwnPassword(session.user) && (
                <button
                  onClick={(e) => {
                    setPasswordDialog(true);
                    e.currentTarget.closest("details").open = false;
                  }}
                >
                  <Key size={17} />
                  修改密码
                </button>
              )}
              {!IS_LIVE && (
                <button
                  onClick={(e) => {
                    setRolePicker(true);
                    e.currentTarget.closest("details").open = false;
                  }}
                >
                  <UsersThree size={17} />
                  切换工作身份
                </button>
              )}
              <button onClick={logout}>
                <SignOut size={17} />
                退出登录
              </button>
            </div>
          </details>
        </div>
      </header>
      <aside className={`sidebar ${mobileNav ? "open" : ""}`}>
        <div className="sidebar-top">党建引领 · 智慧赋能</div>
        <nav
          aria-label="主导航"
          className={school ? "school-navigation" : undefined}
        >
          {school
            ? SCHOOL_NAVIGATION.map((group) => {
                const GroupIcon = schoolIcons[group.icon];
                const children = group.items.filter(([id]) =>
                  navItems.some((item) => item.id === id),
                );
                const expanded = expandedGroup === group.id;
                return (
                  <div className="school-nav-group" key={group.id}>
                    <button
                      className={`nav-link school-primary-nav ${schoolGroup?.id === group.id ? "active" : ""}`}
                      aria-expanded={expanded}
                      aria-controls={`navigation-${group.id}`}
                      onClick={() => {
                        if (schoolGroup?.id !== group.id && children.length)
                          navigate(children[0][0]);
                        setExpandedGroup(expanded ? "" : group.id);
                      }}
                    >
                      <GroupIcon
                        size={20}
                        weight={
                          schoolGroup?.id === group.id ? "fill" : "regular"
                        }
                      />
                      <span>{group.label}</span>
                      <CaretDown
                        size={13}
                        className={expanded ? "expanded" : ""}
                      />
                    </button>
                    {expanded && (
                      <div
                        className="school-subnav"
                        id={`navigation-${group.id}`}
                      >
                        {children.map(([id, label]) => (
                          <a
                            key={id}
                            href={`#/${id}`}
                            className={`school-subnav-link ${route === id ? "active" : ""}`}
                            aria-current={route === id ? "page" : undefined}
                            onClick={(e) => {
                              e.preventDefault();
                              navigate(id);
                            }}
                          >
                            {label}
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })
            : navItems.map((item) => (
                <div key={item.id}>
                  {item.section && (
                    <div className="nav-section">{item.section}</div>
                  )}
                  <a
                    href={`#/${item.id}`}
                    className={`nav-link ${route === item.id ? "active" : ""}`}
                    aria-current={route === item.id ? "page" : undefined}
                  >
                    <item.icon
                      size={20}
                      weight={route === item.id ? "fill" : "regular"}
                    />
                    <span>
                      {isSelfService(session.user) && item.id === "assistant"
                        ? "制度问答"
                        : item.label}
                    </span>
                    {item.badge && (
                      <small className="nav-badge">{item.badge}</small>
                    )}
                    {route === item.id && (
                      <CaretRight size={13} className="nav-caret" />
                    )}
                  </a>
                </div>
              ))}
        </nav>
        <div className="sidebar-footer">
          <ShieldCheck size={17} />
          <span>同心向党 · 笃行致远</span>
        </div>
      </aside>
      {mobileNav && (
        <button
          className="nav-scrim"
          aria-label="关闭导航"
          onClick={() => setMobileNav(false)}
        />
      )}
      <main
        className={`main-content${route === "profile" ? " personal-center-shell" : ""}`}
      >
        <div className="breadcrumbs">
          <span>
            {school
              ? schoolGroup?.label || "学校工作空间"
              : session.user.role === "system_admin"
                ? "平台管理"
                : "工作空间"}
          </span>
          <CaretRight size={12} />
          <span>
            {school
              ? schoolRouteLabel(route) || selected.label
              : selected.label === "首页"
                ? "工作台"
                : selected.label}
          </span>
          <div className="today">
            {new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "long", day: "numeric" }).format(new Date())} <span>{new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", weekday: "long" }).format(new Date())}</span>
          </div>
        </div>
        {storageFailed && (
          <div className="error-box">
            浏览器存储不可用，当前修改可能无法在刷新后保留。
          </div>
        )}
        <div
          className="page-content"
          key={`${session.user.id}:${route}:${JSON.stringify(routeParams)}`}
        >
          <Suspense fallback={<Loading />}>
            {!NAV.some((n) => n.id === route) || !can(selected) ? (
              <div className="permission-empty">
                <ShieldCheck size={48} />
                <h2>
                  {NAV.some((n) => n.id === route)
                    ? "当前账号无此页面的访问权限"
                    : "页面不存在，请返回已授权的工作空间"}
                </h2>
                <button
                  className="button primary"
                  onClick={() =>
                    navigate(selfService ? "self-archive" : "profile")
                  }
                >
                  {selfService ? "前往个人档案" : "前往个人中心"}
                </button>
              </div>
            ) : !IS_LIVE &&
              session.user.role !== "system_admin" &&
              session.user.tenant_id !== "school-1" &&
              !["profile", "assistant", "school-accounts"].includes(route) ? (
              <section className="panel workspace-panel">
                <PageHeader
                  title={selected.label}
                  subtitle="当前学校的数据独立管理"
                />
                <Empty
                  title="本校暂无业务记录"
                  description="新开通学校的人员、材料、会议和统计独立管理；请按授权范围登记本校业务。"
                />
              </section>
            ) : route === "dashboard" ? (
              session.user.role === "system_admin" ? (
                <PlatformHome />
              ) : isSelfService(session.user) ? (
                IS_LIVE ? <LivePersonalWorkspace><PersonalHome /></LivePersonalWorkspace> : <PersonalHome />
              ) : session.user.role === "school_admin" ? (
                <SchoolDashboard />
              ) : (
                IS_LIVE ? <LivePersonalWorkspace><RoleHome /></LivePersonalWorkspace> : <RoleHome />
              )
            ) : session.user.role === "system_admin" && route === "tenants" ? (
              <PlatformTenants />
            ) : session.user.role === "system_admin" && route === "accounts" ? (
              <PlatformAccounts />
            ) : session.user.role === "system_admin" && route === "audit" ? (
              <PlatformAudit />
            ) : route === "operations" ? (
              <PlatformOperations />
            ) : route === "configuration" ? (
              <PlatformConfiguration />
            ) : route === "self-archive" ? (
              <OwnArchive />
            ) : route === "self-materials" ? (
              <OwnMaterials />
            ) : route === "inbox" ? (
              <MaterialInbox />
            ) : route === "reviews" ? (
              school && !IS_LIVE ? (
                <SchoolRecordsPage mode="reviews" />
              ) : (
                <ReviewCenter />
              )
            ) : route === "school-supervision" ? (
              IS_LIVE ? <LiveSchoolBusiness mode="tasks" /> : <SchoolRecordsPage mode="supervision" />
            ) : route === "school-development" ? (
              IS_LIVE ? <LiveBusinessWorkspace><SchoolDevelopment /></LiveBusinessWorkspace> : <SchoolDevelopment />
            ) : route === "school-life" ? (
              IS_LIVE ? <LiveBusinessWorkspace kind="life"><Meetings /></LiveBusinessWorkspace> : <SchoolRecordsPage mode="life" />
            ) : route === "school-learning" ? (
              IS_LIVE ? <LiveLearning /> : <SchoolRecordsPage mode="learning" />
            ) : route === "school-notices" ? (
              IS_LIVE ? <LiveSchoolBusiness mode="notices" /> : <SchoolNotices />
            ) : route === "school-accounts" ? (
              <PlatformAccounts />
            ) : ["school-permissions", "school-rules"].includes(route) ? (
              IS_LIVE ? <LiveSchoolBusiness mode={route.slice(7)} /> : <SchoolManagement mode={route.slice(7)} />
            ) : ["accounts", "tenants", "audit"].includes(route) ? (
              <Administration section={route} />
            ) : route === "development" ? (
              IS_LIVE ? <LiveBusinessWorkspace><DevelopmentWorkbench /></LiveBusinessWorkspace> : <DevelopmentWorkbench />
            ) : route === "assistant" ? (
              <Assistant />
            ) : route === "organization" ? (
              <Organization />
            ) : ["members", "archive"].includes(route) ? (
              <Members mode={route} />
            ) : route === "meetings" ? (
              IS_LIVE ? <LiveBusinessWorkspace kind="life"><Meetings /></LiveBusinessWorkspace> : <Meetings />
            ) : route === "activities" ? (
              IS_LIVE ? <LiveEducation eventOnly /> : <Activities />
            ) : route === "learning" ? (
              IS_LIVE ? <LiveLearning /> : <Learning />
            ) : route === "analytics" ? (
              school ? (
                <SchoolStatistics />
              ) : (
                <Analytics />
              )
            ) : route === "profile" ? (
              <AccountSettings onLogout={logout} />
            ) : route === "knowledge" ? (
              IS_LIVE ? <LiveKnowledge /> : <Knowledge />
            ) : route === "assessment" ? (
              IS_LIVE ? <LiveAssessment /> : school ? (
                <SchoolRecordsPage mode="assessment" />
              ) : (
                <Assessment />
              )
            ) : route === "settings" ? (
              <Settings />
            ) : null}
          </Suspense>
        </div>
        <footer className="app-footer">
          高校智慧党建平台 <span>·</span> 党建引领发展，智慧连接未来
        </footer>
      </main>
      {passwordDialog && (
        <PasswordDialog
          onClose={() => setPasswordDialog(false)}
          onChanged={() => {
            clearSession();
            setSession(null);
            setPasswordDialog(false);
            navigate("login");
            notify("密码已修改，请使用新密码重新登录。");
          }}
        />
      )}
      {showSearch && (
        <Modal title={`搜索“${search}”`} onClose={() => setShowSearch(false)}>
          <div className="search-results">
            {results.length > 0 && <h3>功能页面</h3>}
            {results.map((n) => (
              <button
                key={n.id}
                onClick={() => {
                  navigate(n.id);
                  setShowSearch(false);
                }}
              >
                <n.icon size={20} />
                {n.label}
                <CaretRight size={15} />
              </button>
            ))}
            {memberResults.length > 0 && <h3>党员档案</h3>}
            {memberResults.map((m) => (
              <button
                key={m.id}
                onClick={() => {
                  navigate("members", { query: m.name });
                  setShowSearch(false);
                }}
              >
                <UserCircle size={20} />
                <span>
                  {m.name}
                  <small>{m.organization}</small>
                </span>
                <CaretRight size={15} />
              </button>
            ))}
            {results.length === 0 && memberResults.length === 0 && (
              <p>没有找到相关结果，请调整关键词。</p>
            )}
          </div>
        </Modal>
      )}
      {rolePicker && (
        <Modal title="切换工作身份" wide onClose={() => setRolePicker(false)}>
          <p className="role-picker-note">
            不同角色展示各自的工作台和组织范围。教师／学生属于人员身份，均使用普通党员的本人服务权限。
          </p>
          <div className="persona-grid">
            {DEMO_PERSONAS.map((p) => (
              <button
                key={p.id}
                disabled={
                  !demoAccountAvailable(
                    data.accounts.find((a) => a.id === p.user.id),
                    data.tenants,
                  )
                }
                className={session.user.id === p.user.id ? "active" : ""}
                onClick={() => switchRole(p.id)}
              >
                <span className="persona-icon">
                  <UserCircle size={28} weight="duotone" />
                </span>
                <div>
                  <h3>{p.title}</h3>
                  <p>
                    {p.user.name} · {p.user.username}
                  </p>
                  <small>{scopeLabel(p.user)}</small>
                </div>
                {session.user.id === p.user.id && (
                  <ShieldCheck size={17} weight="fill" />
                )}
              </button>
            ))}
          </div>
          <div className="inline-note">
            请选择已开通的工作身份。切换后，可办理事项以该账号的角色和授权范围为准。
          </div>
        </Modal>
      )}
    </div>
  );
}
function Application() {
  const { resetPrivateData, data } = useStore();
  const [requestedRoute, setRoute] = useState(
    () =>
      window.location.hash.replace("#/", "").split("?")[0] ||
      (IS_LIVE ? "login" : "dashboard"),
  );
  const [routeParams, setRouteParams] = useState({});
  const [session, setSession] = useState(() =>
    IS_LIVE
      ? getSession()
      : normalizeDemoSession(getSession(), data.accounts, data.tenants),
  );
  const route =
    isSelfService(session?.user) && requestedRoute === "profile"
      ? "self-archive"
      : requestedRoute;
  useEffect(() => {
    if (route === requestedRoute) return;
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}#/${route}`,
    );
    setRoute(route);
  }, [route, requestedRoute]);
  useEffect(() => {
    if (!IS_LIVE && session) saveSession(session);
  }, [session]);
  useEffect(() => {
    if (IS_LIVE || !session?.user) return;
    function checkPasswordVersion() {
      try {
        if (
          demoPasswordService().revision(session.user) ===
          (session.passwordVersion || 0)
        )
          return;
      } catch {
        /* Unreadable security state must not retain an authenticated demo session. */
      }
      clearSession();
      setSession(null);
      window.location.hash = "/login";
    }
    checkPasswordVersion();
    return subscribePasswordSecurity(checkPasswordVersion);
  }, [session?.user?.id, session?.user?.tenant_id, session?.passwordVersion]);
  useEffect(() => {
    if (IS_LIVE || !session?.user) return;
    const account = data.accounts.find((a) => a.id === session.user.id);
    if (!demoAccountAvailable(account, data.tenants)) {
      clearSession();
      setSession(null);
      window.location.hash = "/login";
    }
  }, [data.accounts, data.tenants, session?.user?.id]);
  useEffect(() => {
    resetPrivateData();
  }, [session?.user?.id, session?.user?.username, resetPrivateData]);
  function navigate(id, params = {}) {
    setRouteParams(params);
    if (id === route) {
      setRoute(id);
    } else window.location.hash = "/" + id;
  }
  useEffect(() => {
    const onHash = () =>
      setRoute(
        window.location.hash.replace("#/", "").split("?")[0] || "dashboard",
      );
    const expired = () => {
      setSession(null);
      window.location.hash = "/login";
    };
    window.addEventListener("hashchange", onHash);
    window.addEventListener("dangjian:expired", expired);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("dangjian:expired", expired);
    };
  }, []);
  useEffect(() => {
    document.title = `${route === "profile" ? "个人中心" : route === "login" ? "登录" : session?.user?.role === "school_admin" ? schoolNavigationGroup(route)?.label || "学校工作台" : navForUser(session?.user).find((n) => n.id === route)?.label || NAV.find((n) => n.id === route)?.label || "工作台"} · 高校智慧党建平台`;
  }, [route, session?.user?.role]);
  function can(item) {
    if (session?.user?.role === "school_admin" && item?.id === "analytics")
      return canAccess(
        session,
        { ...item, demo: false, permission: "member.query" },
        IS_LIVE,
      );
    return canAccess(session, item, IS_LIVE);
  }
  return (
    <AppContext.Provider
      value={{
        route,
        routeParams,
        navigate,
        session,
        setSession,
        can,
        allowed: (permission) => hasPermission(session, permission),
      }}
    >
      {route === "login" || !session?.user ? <Login /> : <Shell />}
    </AppContext.Provider>
  );
}
export function App() {
  return (
    <StoreProvider>
      <Application />
    </StoreProvider>
  );
}
