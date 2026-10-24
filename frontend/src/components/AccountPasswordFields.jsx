import { useState } from "react";
import { Eye, EyeSlash } from "@phosphor-icons/react";

export function AccountPasswordFields({ required = false, disabled = false }) {
  const [visible, setVisible] = useState(false);
  return (
    <fieldset
      className="identity-password-fields field full"
      disabled={disabled}
    >
      <legend>{required ? "设置新密码" : "修改密码（选填）"}</legend>
      <p className="muted">
        {required ? "请输入并确认新密码。" : "留空则保留原密码。"}
        原密码不回显，新密码至少8位且不超过72字节。
      </p>
      <div className="identity-password-inputs">
        <label className="field">
          <span>{required && <b>*</b>}新密码</span>
          <input
            name="password"
            type={visible ? "text" : "password"}
            defaultValue=""
            required={required}
            minLength={8}
            maxLength={72}
            autoComplete="new-password"
            placeholder="输入新密码"
          />
        </label>
        <label className="field">
          <span>{required && <b>*</b>}确认新密码</span>
          <input
            name="password_confirmation"
            type={visible ? "text" : "password"}
            defaultValue=""
            required={required}
            maxLength={72}
            autoComplete="new-password"
            placeholder="再次输入新密码"
          />
        </label>
      </div>
      <button
        type="button"
        className="text-button link identity-password-visibility"
        aria-pressed={visible}
        onClick={() => setVisible((value) => !value)}
      >
        {visible ? <EyeSlash size={16} /> : <Eye size={16} />}
        {visible ? "隐藏新密码" : "显示新密码"}
      </button>
    </fieldset>
  );
}
