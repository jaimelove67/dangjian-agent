import { request } from "./api.js";

// Read-only operations verified against the reference backend on 2026-10-23.
// Jobs are scoped to the submitting account; operations are scoped to its tenant.
export const platformOpsApi = {
  operations: () => request("/admin/operations"),
  overview: () => request("/admin/operations"),
  health: () =>
    request("/admin/health/ready", {
      rawJson: true,
      acceptNotReady: true,
      timeout: 30000,
    }),
  jobs: (page = 1) => request(`/admin/jobs?page=${page}`),
  runLogs: (page = 1) =>
    request(`/admin/run-logs?page=${page}&page_size=40&result=failed`),
  configuration: () => request("/admin/config"),
  saveConfiguration: (values) =>
    request("/admin/config", { method: "PATCH", body: JSON.stringify(values) }),
  governance: () => request("/admin/governance"),
  saveGovernance: (values) =>
    request("/admin/governance", {
      method: "PATCH",
      body: JSON.stringify(values),
    }),
  notificationChannels: () => request("/admin/notification-channels"),
  retention: () => request("/admin/retention"),
};

export function validatePlatformConfig(section, values) {
  const integer = (value, min, max) =>
    Number.isInteger(Number(value)) &&
    Number(value) >= min &&
    Number(value) <= max;
  const secureUrl = (value) => {
    try {
      const url = new URL(value);
      return (
        url.protocol === "https:" &&
        !url.username &&
        !url.password &&
        !url.search &&
        !url.hash
      );
    } catch {
      return false;
    }
  };
  if (section === "auth") {
    if (!values.password_login && !values.sso_enabled)
      return "请至少保留一种登录方式。";
    if (values.sso_enabled && !secureUrl(values.sso_issuer))
      return "请输入有效的 HTTPS 身份提供方地址，地址中不能包含账号、密码或查询参数。";
    if (!integer(values.session_minutes, 15, 1440))
      return "会话有效期应为 15–1440 的整数分钟。";
  }
  if (section === "notifications" && values.email_enabled) {
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.sender_email))
      return "启用邮件通知时，请填写有效的发件邮箱。";
  }
  if (section === "uploads") {
    if (!integer(values.max_file_mb, 1, 100))
      return "单个文件上限应为 1–100 的整数 MB。";
    if (!values.allowed_extensions?.length) return "请至少允许一种文件格式。";
    if (
      values.allowed_extensions.some(
        (ext) =>
          !["pdf", "docx", "txt", "md", "png", "jpg", "jpeg"].includes(ext),
      )
    )
      return "文件格式必须从平台支持的类型中选择。";
    if (!integer(values.retention_days, 30, 3650))
      return "保留期限应为 30–3650 的整数天数。";
  }
  if (section === "model") {
    if (!values.model_name?.trim()) return "请填写模型名称。";
    if (!secureUrl(values.base_url))
      return "请输入有效的 HTTPS 服务地址，地址中不能包含账号、密码或查询参数。";
    if (!integer(values.timeout_seconds, 5, 300))
      return "请求超时应为 5–300 的整数秒数。";
  }
  if (section === "general") {
    if (
      !values.platform_name?.trim() ||
      values.platform_name.trim().length > 40
    )
      return "平台名称不能为空且不能超过 40 个字符。";
    if (
      values.support_email &&
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.support_email)
    )
      return "请填写有效的服务邮箱。";
  }
  return "";
}
