const at = (hour) => `2026-10-23T${hour}:00+08:00`;
export function platformSeed() {
  return {
    version: 1,
    services: [
      {
        id: "api",
        name: "API 网关",
        description: "业务接口与访问控制",
        status: "healthy",
        latency: 42,
        checked_at: at("10:28"),
      },
      {
        id: "database",
        name: "业务数据库",
        description: "租户与党务业务数据",
        status: "healthy",
        latency: 8,
        checked_at: at("10:28"),
      },
      {
        id: "queue",
        name: "异步任务服务",
        description: "文件解析与索引任务",
        status: "warning",
        latency: 126,
        checked_at: at("10:28"),
      },
      {
        id: "storage",
        name: "私有文件存储",
        description: "材料原件与附件",
        status: "healthy",
        latency: 25,
        checked_at: at("10:28"),
      },
      {
        id: "model",
        name: "模型服务",
        description: "知识问答与向量检索",
        status: "healthy",
        latency: 386,
        checked_at: at("10:28"),
      },
    ],
    incidents: [
      {
        id: "incident-1",
        endpoint: "POST /api/v1/knowledge-docs",
        message: "海川师范大学有文件解析失败，请核对文件格式后重试。",
        severity: "high",
        status: "open",
        count: 2,
        last_seen: at("10:21"),
      },
      {
        id: "incident-2",
        endpoint: "POST /api/v1/auth/login",
        message: "同一来源连续登录失败，已触发临时访问限制。",
        severity: "medium",
        status: "open",
        count: 5,
        last_seen: at("09:45"),
      },
    ],
    jobs: [
      {
        id: "job-1",
        name: "2026 年度制度文件解析",
        type: "文件解析",
        status: "failed",
        tenant_name: "海川师范大学",
        tenant_id: "school-2",
        created_at: at("10:18"),
        error: "文件正文为空，请核对原件后重新提交。",
        attempts: 1,
      },
      {
        id: "job-2",
        name: "学习资料向量索引更新",
        type: "向量索引",
        status: "failed",
        tenant_name: "示范大学",
        tenant_id: "school-1",
        created_at: at("09:52"),
        error: "模型服务请求超时，索引更新未完成。",
        attempts: 1,
      },
      {
        id: "job-3",
        name: "10 月新增材料索引",
        type: "向量索引",
        status: "processing",
        tenant_name: "示范大学",
        tenant_id: "school-1",
        created_at: at("10:24"),
        error: "",
        attempts: 1,
      },
      {
        id: "job-4",
        name: "党员培养提醒生成",
        type: "到期提醒",
        status: "completed",
        tenant_name: "海川师范大学",
        tenant_id: "school-2",
        created_at: at("09:10"),
        error: "",
        attempts: 1,
      },
    ],
    storage: {
      used_gb: 128.6,
      capacity_gb: 500,
      material_gb: 96.2,
      backup_gb: 32.4,
    },
    backups: [
      {
        id: "backup-1",
        name: "平台每日备份 2026-10-23",
        status: "completed",
        size_mb: 32400,
        created_at: at("02:00"),
        scope: "平台配置与业务数据",
        restore_drills: [],
        checksum: "",
      },
      {
        id: "backup-2",
        name: "平台每日备份 2026-10-22",
        status: "completed",
        size_mb: 32080,
        created_at: "2026-10-22T02:00:00+08:00",
        scope: "平台配置与业务数据",
        restore_drills: [],
        checksum: "",
      },
    ],
    sessions: [
      {
        id: "session-current",
        user_id: "demo-platform",
        username: "platform",
        tenant_id: "platform-1",
        client_label: "Chrome · Windows",
        ip: "127.0.0.1",
        last_seen_at: at("10:28"),
        created_at: at("09:00"),
        is_current: true,
        is_active: true,
      },
      {
        id: "session-school",
        user_id: "demo-school",
        username: "admin",
        tenant_id: "school-1",
        client_label: "Edge · Windows",
        ip: "192.0.2.21",
        last_seen_at: at("10:12"),
        created_at: at("08:30"),
        is_current: false,
        is_active: true,
      },
      {
        id: "session-history",
        user_id: "demo-school",
        username: "admin",
        tenant_id: "school-1",
        client_label: "Chrome · macOS",
        ip: "192.0.2.38",
        last_seen_at: "2026-10-22T17:30:00+08:00",
        created_at: "2026-10-22T08:30:00+08:00",
        is_current: false,
        is_active: false,
      },
    ],
    usage: [
      {
        tenant_id: "school-1",
        active_accounts: 7,
        storage_bytes: 82.4 * 1024 ** 3,
        storage_limit_bytes: 200 * 1024 ** 3,
        files_count: 1284,
        task_count: 42,
        period_label: "2026 年 10 月",
      },
      {
        tenant_id: "school-2",
        active_accounts: 1,
        storage_bytes: 46.2 * 1024 ** 3,
        storage_limit_bytes: 200 * 1024 ** 3,
        files_count: 756,
        task_count: 28,
        period_label: "2026 年 10 月",
      },
      {
        tenant_id: "school-3",
        active_accounts: 1,
        storage_bytes: 0,
        storage_limit_bytes: 100 * 1024 ** 3,
        files_count: 0,
        task_count: 0,
        period_label: "2026 年 10 月",
      },
    ],
    config: {
      auth: {
        password_login: true,
        sso_enabled: false,
        sso_issuer: "",
        session_minutes: 120,
        mfa_required: false,
      },
      notifications: {
        in_app: true,
        email_enabled: false,
        sender_email: "",
        webhook_enabled: false,
      },
      uploads: {
        max_file_mb: 20,
        allowed_extensions: ["pdf", "docx", "txt", "md", "png", "jpg", "jpeg"],
        retention_days: 365,
      },
      model: {
        provider: "qwen",
        base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name: "qwen-plus",
        timeout_seconds: 60,
        enabled: true,
        credential_configured: false,
      },
      general: {
        platform_name: "高校智慧党建平台",
        support_email: "support@example.edu.cn",
        timezone: "Asia/Shanghai",
        maintenance_mode: false,
      },
    },
    configSavedAt: {},
  };
}
export function extendPlatformData(data) {
  const initial = platformSeed(),
    saved = data.platform || {};
  const config = Object.fromEntries(
    Object.entries(initial.config).map(([key, value]) => [
      key,
      { ...value, ...saved.config?.[key] },
    ]),
  );
  const append = (items, extra) => [
    ...items,
    ...extra.filter((e) => !items.some((i) => i.id === e.id)),
  ];
  const result = { ...data, platform: { ...initial, ...saved, config } };
  if (!saved.version) {
    result.tenants = data.tenants.map((t) =>
      t.id === "school-1"
        ? {
            contact_name: "李老师",
            contact_email: "admin@example.edu.cn",
            contact_phone: "010-68000001",
            service_plan: "标准版",
            school_admin_user_id: "demo-school",
            ...t,
          }
        : t,
    );
    result.tenants = append(result.tenants, [
      {
        id: "school-2",
        name: "海川师范大学",
        tenant_type: "school",
        parent_id: "platform-1",
        is_active: true,
        contact_name: "陈老师",
        contact_email: "admin@haichuan.example.edu.cn",
        service_plan: "标准版",
        school_admin_user_id: "demo-school-2-admin",
      },
      {
        id: "school-3",
        name: "北辰理工大学",
        tenant_type: "school",
        parent_id: "platform-1",
        is_active: false,
        contact_name: "张老师",
        contact_email: "admin@beichen.example.edu.cn",
        service_plan: "试用版",
        school_admin_user_id: "demo-school-3-admin",
      },
    ]);
    result.accounts = data.accounts.map((a) =>
      a.id === "demo-platform" ? { ...a, tenant_id: "platform-1" } : a,
    );
    for (const [n, name] of [
      [2, "陈老师"],
      [3, "张老师"],
    ])
      result.accounts = append(result.accounts, [
        {
          id: `demo-school-${n}-admin`,
          username: `school${n}_admin`,
          name,
          role: "school_admin",
          tenant_id: `school-${n}`,
          org_unit_id: `school-${n}`,
          org_name: n === 2 ? "海川师范大学党委" : "北辰理工大学党委",
          is_active: true,
        },
      ]);
    const events = [
      [
        "login",
        "platform_login",
        "平台管理员",
        "user",
        "demo-platform",
        "success",
        "127.0.0.1",
        "管理员登录成功。",
      ],
      [
        "permission",
        "update_user_role",
        "平台管理员",
        "user",
        "demo-school",
        "success",
        "127.0.0.1",
        "核对学校管理员角色与组织范围。",
      ],
      [
        "material",
        "download_material",
        "王组织员",
        "personal_material",
        "demo-material-student",
        "success",
        "192.0.2.21",
        "授权组织人员下载材料原件。",
      ],
      [
        "anomaly",
        "login_denied",
        "未登录访问",
        "auth",
        "anonymous",
        "denied",
        "192.0.2.99",
        "连续认证失败，访问已被限制。",
      ],
    ];
    result.auditEntries = append(
      data.auditEntries,
      events.map(
        (
          [
            category,
            action,
            user_name,
            resource_type,
            resource_id,
            result,
            ip,
            detail,
          ],
          i,
        ) => ({
          id: `platform-audit-${i}`,
          category,
          action,
          user_name,
          actor_name: user_name,
          resource_type,
          resource_id,
          result,
          ip,
          detail,
          tenant_id: i === 2 ? "school-1" : "platform-1",
          created_at: at(`10:${10 + i}`),
          request_id: `local-platform-trace-${i}`,
        }),
      ),
    );
    result.platform.version = 1;
  }
  return result;
}
export function platformSummary(data) {
  const state = data.platform || {},
    schools = data.tenants.filter((t) => t.tenant_type === "school");
  return {
    schools: schools.length,
    activeSchools: schools.filter((t) => t.is_active).length,
    accounts: data.accounts.length,
    activeAccounts: data.accounts.filter((a) => a.is_active).length,
    services: (state.services || []).length,
    healthyServices: (state.services || []).filter(
      (s) => s.status === "healthy",
    ).length,
    incidents: (state.incidents || []).filter((i) => i.status === "open")
      .length,
    failedJobs: (state.jobs || []).filter((j) => j.status === "failed").length,
  };
}
