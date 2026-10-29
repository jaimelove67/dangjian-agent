import { useEffect, useState } from "react";
import {
  UsersThree,
  Buildings,
  ClipboardText,
  FileText,
  ArrowRight,
  CalendarBlank,
  ShieldCheck,
  IdentificationCard,
  SquaresFour,
  ChartBar,
  Clock,
  CheckCircle,
  Sparkle,
} from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE, backend } from "../api";
import { roleApi } from "../role-api";
import { useManagedWorkspace } from "../role-hooks";
import { ROLE_INFO, scopeLabel, roleLabel, memberInScope } from "../roles";
import { PanelTitle, Badge, ErrorBox, Empty } from "../components";
import { PublicationsPanel } from "../components/PublicationsPanel";
import { HomeBanner, HomeAssistant } from "../components/HomeWorkspace";
export function RoleHome() {
  const { session, navigate, can } = useApp();
  const { data } = useStore();
  const w = useManagedWorkspace();
  const [remote, setRemote] = useState(null);
  const [error, setError] = useState(null);
  const platform = session.user.role === "system_admin",
    department = session.user.role === "department_admin",
    secretary = session.user.role === "branch_secretary";
  useEffect(() => {
    if (!IS_LIVE || !platform) return;
    let active = true;
    Promise.all([
      roleApi.tenants(),
      roleApi.users(),
      roleApi.operations(),
      backend.health(),
    ])
      .then(([tenants, users, operations, health]) => {
        if (active)
          setRemote({
            tenants: tenants.items || [],
            users: users.items || [],
            operations,
            health,
          });
      })
      .catch((e) => {
        if (active) setError(e);
      });
    return () => {
      active = false;
    };
  }, [platform, session.user.id]);
  const memberIds = new Set(w.members.map((m) => m.id));
  const materials = data.personalMaterials.filter((m) =>
    memberIds.has(m.profile_id),
  );
  const pending = w.meetings.filter((m) => m.status === "待审核");
  const metrics = platform
    ? [
        {
          label: "授权租户",
          value: IS_LIVE
            ? (remote?.tenants.length ?? "—")
            : data.tenants.filter((t) => t.tenant_type !== "platform").length,
          unit: "个",
          icon: Buildings,
          color: "red",
        },
        {
          label: "登录账号",
          value: IS_LIVE ? (remote?.users.length ?? "—") : data.accounts.length,
          unit: "个",
          icon: UsersThree,
          color: "blue",
        },
        {
          label: "审计记录",
          value: IS_LIVE ? "—" : data.auditEntries.length,
          unit: "条",
          icon: ShieldCheck,
          color: "green",
        },
        {
          label: "就绪状态",
          value: IS_LIVE
            ? remote?.health.status === "ready"
              ? "已就绪"
              : "检查中"
            : "运行正常",
          icon: CheckCircle,
          color: "orange",
        },
      ]
    : [
        {
          label: department ? "本院在册党员" : "支部在册党员",
          value: w.members.filter(m => ["正式党员", "预备党员"].includes(m.stage)).length,
          unit: "人",
          icon: UsersThree,
          color: "red",
        },
        {
          label: department ? "所属党支部" : "待审核会议",
          value: department ? w.orgs.length : pending.length,
          unit: department ? "个" : "项",
          icon: department ? Buildings : ClipboardText,
          color: "orange",
        },
        {
          label: "已接收个人材料",
          value: IS_LIVE ? "—" : materials.length,
          unit: "份",
          icon: FileText,
          color: "blue",
        },
        {
          label: "申请与培养人员",
          value: w.members.filter(m => ["入党申请人", "入党积极分子", "发展对象"].includes(m.stage)).length,
          unit: "人",
          icon: IdentificationCard,
          color: "green",
        },
      ];
  const shortcuts = (
    platform
      ? [
          ["accounts", "账号管理", "按角色与组织创建账号", UsersThree],
          ["tenants", "租户管理", "维护学校与组织归属", Buildings],
          ["audit", "审计日志", "回看操作与授权轨迹", ShieldCheck],
          ["settings", "系统管理", "查看配置和接入状态", SquaresFour],
        ]
      : department
        ? [
            ["organization", "组织建设", "查看本院支部设置", Buildings],
            ["reviews", "审核工作台", "核对组织生活与业务材料", ClipboardText],
            ["assessment", "年度考核", "跟进指标和佐证归集", ChartBar],
            [
              "development",
              "党员发展",
              "查看本院培养与发展进程",
              IdentificationCard,
            ],
          ]
        : secretary
          ? [
              [
                "reviews",
                "审核工作台",
                "核对会议纪要并给出意见",
                ClipboardText,
              ],
              ["meetings", "组织生活", "登记会议、议程和纪要", CalendarBlank],
              [
                "development",
                "党员发展",
                "核对材料与人工阶段办理",
                IdentificationCard,
              ],
              ["inbox", "材料接收", "查阅本支部党员提交原件", FileText],
            ]
          : [
              ["inbox", "材料接收", "逐人接收与下载个人材料", FileText],
              [
                "development",
                "发展办理",
                "登记材料、培养记录和阶段",
                IdentificationCard,
              ],
              ["members", "党员名册", "维护本支部人员档案", UsersThree],
              ["meetings", "组织生活", "整理会议议程与纪要", CalendarBlank],
            ]
  ).filter(([id]) =>
    can({
      id,
      permission:
        id === "accounts" || id === "tenants"
          ? "admin.identity"
          : id === "audit"
            ? "admin.audit"
            : id === "reviews"
              ? "admin.review"
              : id === "settings"
                ? "admin.config"
                : id === "assessment"
                  ? "assessment.query"
                  : id === "meetings"
                    ? "meeting.query"
                    : "member.query",
      ...(id === "accounts" || id === "tenants"
        ? { roles: ["system_admin"] }
        : {}),
    }),
  );
  return <div className="home-workspace role-home">
    <HomeBanner title={`${roleLabel(session.user)}工作台`} description={scopeLabel(session.user)} />
    {(error || w.error) && <ErrorBox error={error || w.error} retry={w.reload} />}
    <div className="home-primary-grid">
      <PublicationsPanel key={`${session.user.tenant_id}:${session.user.id}`} limit={5} />
      <section className="panel">
        <PanelTitle title={department ? "支部工作概览" : secretary ? "待办与审核" : "材料接收动态"} action="查看全部" onAction={() => navigate(department ? "organization" : secretary ? "reviews" : "inbox")} />
        {department ? <>{w.orgs.slice(0, 4).map(org => <button className="home-action-row" key={org.id} onClick={() => navigate("members", { organization: org.name })}><span className="home-row-icon"><Buildings size={22} /></span><span><strong>{org.name}</strong><small>{w.members.filter(m => m.orgId === org.id && ["正式党员", "预备党员"].includes(m.stage)).length} 名在册党员 · {w.meetings.filter(m => m.orgId === org.id && m.status === "待审核").length} 项会议待审核</small></span><ArrowRight size={16} /></button>)}{!w.orgs.length && <Empty title="暂无授权支部记录" />}</> : secretary ? <>{pending.slice(0, 4).map(meeting => <button className="home-action-row" key={meeting.id} onClick={() => navigate("reviews")}><span className="home-row-icon"><ClipboardText size={22} /></span><span><strong>{meeting.title}</strong><small>{meeting.date} · 待人工审核</small></span><Badge tone="orange">待审核</Badge></button>)}{!pending.length && <Empty title="暂无待审核会议" description="已提交且需要审核的组织生活记录会显示在这里。" />}<button className="home-action-row" onClick={() => navigate("development")}><span className="home-row-icon"><IdentificationCard size={22} /></span><span><strong>查看培养发展进程</strong><small>核对材料、培养记录与办理依据</small></span><ArrowRight size={16} /></button></> : <>{materials.slice(0, 4).map(material => <button className="home-action-row" key={material.id} onClick={() => navigate("inbox", { profileId: material.profile_id })}><span className="home-row-icon"><FileText size={22} /></span><span><strong>{material.title}</strong><small>{w.members.find(m => m.id === material.profile_id)?.name} · 个人提交</small></span><Badge tone="blue">已提交</Badge></button>)}{!materials.length && <Empty title="暂无接收材料" description={IS_LIVE ? "请进入材料接收查看授权人员的提交记录。" : "当前组织尚无个人提交材料。"} />}</>}
      </section>
    </div>
    <div className="role-metrics four">{metrics.map(metric => <div key={metric.label}><span className={`metric-icon ${metric.color}`}><metric.icon size={24} /></span><div><p>{metric.label}</p><strong>{w.loading || w.error ? "—" : metric.value}<small>{metric.unit}</small></strong></div></div>)}</div>
    <div className="home-secondary-grid">
      <section className="panel role-shortcuts"><PanelTitle title="常用办理" /><div className="role-shortcut-grid">{shortcuts.map(([id, title, desc, Icon]) => <button key={id} onClick={() => navigate(id)}><span className="shortcut-icon"><Icon size={24} /></span><h3>{title}</h3><p>{desc}</p><ArrowRight size={16} /></button>)}</div></section>
      <HomeAssistant />
    </div>
    {IS_LIVE && <p className="page-note">工作概览按当前已加载的授权记录统计。</p>}
  </div>;
}
