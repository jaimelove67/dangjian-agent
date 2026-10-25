export const APPROVED_RESET_PASSWORD_RULE = "学校名称拼音首字母_姓名拼音首字母";

const initials = (pinyin, value, label) => {
  const text = String(value || "").replace(/\s+/g, "");
  if (!text) throw new Error(`${label}不能为空。`);
  const result = pinyin(text, {
    pattern: "first",
    toneType: "none",
  })
    .replace(/[^a-z0-9]/gi, "")
    .toLowerCase();
  if (!result) throw new Error(`${label}无法生成拼音首字母。`);
  return result;
};

export async function approvedResetPassword(account, tenants = []) {
  const { pinyin } = await import("pinyin-pro");
  const tenant = tenants.find((item) => item.id === account?.tenant_id);
  const password = `${initials(pinyin, tenant?.name, "学校名称")}_${initials(pinyin, account?.name, "姓名")}`;
  if (new TextEncoder().encode(password).length > 72)
    throw new Error("学校名称和姓名过长，暂时无法生成默认密码。");
  return password;
}
