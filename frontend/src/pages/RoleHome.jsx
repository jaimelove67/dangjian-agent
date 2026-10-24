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
import { PanelTitle, Badge, ErrorBox } from "../components";
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
          value: w.members.length,
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
          label: "培养发展对象",
          value: w.members.filter((m) => m.stage !== "正式党员").length,
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
  return (
    <div className="role-workspace">
      <section className="role-welcome">
        <div>
          <span className="eyebrow">
            {roleLabel(session.user)}工作台 <span>·</span>{" "}
            {scopeLabel(session.user)}
          </span>
          <h1>
            {platform
              ? "让管理有序，让责任可追溯"
              : department
                ? "掌握院系进度，推动支部落实"
                : secretary
                  ? "抓好支部工作，办好每一件实事"
                  : "材料有序接收，党务规范办理"}
          </h1>
          <p>{ROLE_INFO[session.user.role].subtitle}</p>
        </div>
        <span className="welcome-seal">
          <ShieldCheck size={34} weight="duotone" />
          <span>按组织范围授权</span>
        </span>
      </section>
      {(error || w.error) && (
        <ErrorBox error={error || w.error} retry={w.reload} />
      )}
      <div className="role-metrics four">
        {metrics.map((m) => (
          <div key={m.label}>
            <span className={`metric-icon ${m.color}`}>
              <m.icon size={25} weight="duotone" />
            </span>
            <div>
              <p>{m.label}</p>
              <strong
                className={
                  typeof m.value === "string" && m.value.length > 3
                    ? "text-metric"
                    : ""
                }
              >
                {m.value}
                <small>{m.unit}</small>
              </strong>
            </div>
          </div>
        ))}
      </div>
      <section className="panel role-shortcuts">
        <PanelTitle title="常用办理" />
        <div className="role-shortcut-grid">
          {shortcuts.map(([id, title, desc, Icon]) => (
            <button key={id} onClick={() => navigate(id)}>
              <span className="shortcut-icon">
                <Icon size={25} weight="duotone" />
              </span>
              <h3>{title}</h3>
              <p>{desc}</p>
              <ArrowRight size={16} />
            </button>
          ))}
        </div>
      </section>
      <div className="role-columns">
        <section className="panel">
          <PanelTitle
            title={
              platform
                ? "系统管理事项"
                : department
                  ? "支部工作概览"
                  : secretary
                    ? "待办与审核"
                    : "材料接收动态"
            }
            action="查看全部"
            onAction={() =>
              navigate(
                platform
                  ? "audit"
                  : department
                    ? "organization"
                    : secretary
                      ? "reviews"
                      : "inbox",
              )
            }
          />
          {platform ? (
            <div className="role-admin-tasks">
              <button onClick={() => navigate("accounts")}>
                <UsersThree size={22} />
                <div>
                  <h3>账号与人员归属核对</h3>
                  <p>管理权限与教师／学生身份分别维护</p>
                </div>
                <ArrowRight size={16} />
              </button>
              <button onClick={() => navigate("tenants")}>
                <Buildings size={22} />
                <div>
                  <h3>租户与学校信息</h3>
                  <p>新增租户仅登记组织信息，不自动分配权限</p>
                </div>
                <ArrowRight size={16} />
              </button>
              <button onClick={() => navigate("audit")}>
                <ShieldCheck size={22} />
                <div>
                  <h3>操作审计与追踪</h3>
                  <p>按动作和结果回看操作留痕</p>
                </div>
                <ArrowRight size={16} />
              </button>
            </div>
          ) : department ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>党支部</th>
                    <th>在册党员</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {w.orgs.map((org) => (
                    <tr key={org.id}>
                      <td>{org.name}</td>
                      <td>
                        {w.members.filter((m) => m.orgId === org.id).length} 人
                      </td>
                      <td>
                        <button
                          className="text-button link"
                          onClick={() =>
                            navigate("members", { organization: org.name })
                          }
                        >
                          查看名册
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : secretary ? (
            <div className="role-admin-tasks">
              {pending.map((m) => (
                <button key={m.id} onClick={() => navigate("reviews")}>
                  <ClipboardText size={23} />
                  <div>
                    <h3>{m.title}</h3>
                    <p>{m.date} · 会议纪要待独立人工审核</p>
                  </div>
                  <Badge tone="orange">待审核</Badge>
                </button>
              ))}
              {!pending.length && (
                <div className="subtle-empty">
                  当前暂无待审核的组织生活记录。
                </div>
              )}
              <button onClick={() => navigate("development")}>
                <IdentificationCard size={23} />
                <div>
                  <h3>核对培养发展进程</h3>
                  <p>查看材料、培养记录与人工流转依据</p>
                </div>
                <ArrowRight size={16} />
              </button>
            </div>
          ) : (
            <div className="compact-material-list">
              {materials.slice(0, 4).map((m) => (
                <button
                  key={m.id}
                  onClick={() => navigate("inbox", { profileId: m.profile_id })}
                >
                  <FileText size={22} />
                  <div>
                    <h3>{m.title}</h3>
                    <p>
                      {w.members.find((p) => p.id === m.profile_id)?.name} ·{" "}
                      {m.created_at.slice(0, 10)}
                    </p>
                  </div>
                  <Badge tone="blue">已提交</Badge>
                </button>
              ))}
              {!materials.length && (
                <div className="subtle-empty">
                  材料会按当前账号的组织授权范围接收。
                </div>
              )}
            </div>
          )}
        </section>
        <section className="panel">
          <PanelTitle title={platform ? "运行与管理边界" : "近期工作提示"} />
          <div className="work-guidance">
            {(platform
              ? [
                  [
                    "账号开户",
                    "仅平台管理员可进入开户页，按组织类型分配角色。",
                  ],
                  ["权限范围", "可办理事项以当前账号的角色、所属学校和组织授权为准。"],
                  ["审计留痕", "查看与导出仅限授权范围，不提供物理清理操作。"],
                ]
              : [
                  [
                    "组织生活",
                    "纪要提交人与审核人应分开，审核后按学校政策归档。",
                  ],
                  ["个人材料", "接收表示可查阅，不等同于审核通过或阶段变更。"],
                  ["人工办理", "党员发展和考核结论均须由有权限人员核验。"],
                ]
            ).map(([title, desc], i) => (
              <div key={title}>
                <span>0{i + 1}</span>
                <div>
                  <h3>{title}</h3>
                  <p>{desc}</p>
                </div>
              </div>
            ))}
          </div>
          <button
            className="work-guidance-link"
            onClick={() => navigate("assistant")}
          >
            <Sparkle size={17} />
            需要制度依据？向党建智能体提问
            <ArrowRight size={14} />
          </button>
        </section>
      </div>
      {IS_LIVE && (
        <p className="page-note">
          工作概览按当前已加载的授权记录统计；正式业务统计以服务端工作台为准。
        </p>
      )}
    </div>
  );
}
