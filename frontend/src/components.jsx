import { useEffect, useRef } from "react";
import {
  MagnifyingGlass,
  X,
  CaretDown,
  CaretRight,
  CheckCircle,
  WarningCircle,
  CircleNotch,
} from "@phosphor-icons/react";
export function SearchInput({
  value,
  onChange,
  placeholder = "请输入关键词搜索",
  className = "",
  ...props
}) {
  return (
    <div className={`search-input ${className}`}>
      <MagnifyingGlass size={16} />
      <input
        aria-label={placeholder}
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        {...props}
      />
      {value && (
        <button
          className="icon-button small"
          aria-label="清空搜索"
          onClick={() => onChange({ target: { value: "" } })}
        >
          <X size={12} />
        </button>
      )}
    </div>
  );
}
export function Select({ children, label, ...props }) {
  return (
    <div className="select-wrap">
      <select aria-label={label} {...props}>
        {children}
      </select>
      <CaretDown size={12} />
    </div>
  );
}
export function Badge({ children, tone }) {
  const color =
    tone ||
    (["正常", "已归档", "已结束", "已完成", "现行有效", "正式党员"].includes(
      children,
    )
      ? "green"
      : ["未开始", "待召开", "待复核", "预备党员", "待审核"].includes(children)
        ? "orange"
        : "blue");
  return <span className={`badge ${color}`}>{children}</span>;
}
export function PageHeader({ title, subtitle, action }) {
  return (
    <div className="page-header">
      <div>
        <div className="page-title">
          <i />
          {title}
        </div>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
export function PanelTitle({ title, action, onAction, children }) {
  return (
    <div className="panel-title">
      <h2>
        <i />
        {title}
        {children}
      </h2>
      {action && (
        <button className="text-button muted" onClick={onAction}>
          {action}
          <CaretRight size={13} />
        </button>
      )}
    </div>
  );
}
export function Tabs({ items, active, onChange, compact = false }) {
  return (
    <div className={`tabs ${compact ? "compact" : ""}`} role="tablist">
      {items.map((item) => {
        const id = typeof item === "string" ? item : item.id;
        const label = typeof item === "string" ? item : item.label;
        return (
          <button
            key={id}
            role="tab"
            aria-selected={active === id}
            className={active === id ? "active" : ""}
            onClick={() => onChange(id)}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
  flat = false,
  className = "",
}) {
  const ref = useRef(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={`modal ${wide ? "wide" : ""} ${flat ? "flat" : ""} ${className}`}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          const r = e.currentTarget.getBoundingClientRect();
          if (
            e.clientX < r.left ||
            e.clientX > r.right ||
            e.clientY < r.top ||
            e.clientY > r.bottom
          )
            onClose();
        }
      }}
      aria-labelledby="modal-title"
    >
      <div className="modal-heading">
        <h2 id="modal-title">{title}</h2>
        <button className="icon-button" aria-label="关闭弹窗" onClick={onClose}>
          <X size={21} />
        </button>
      </div>
      <div className="modal-body">{children}</div>
    </dialog>
  );
}
export function Field({ label, children, required, full }) {
  return (
    <label className={`field ${full ? "full" : ""}`}>
      <span>
        {required && <b>*</b>}
        {label}
      </span>
      {children}
    </label>
  );
}
export function Empty({
  title = "暂无符合条件的记录",
  description = "试试调整搜索关键词或筛选条件。",
  action,
}) {
  return (
    <div className="empty">
      <MagnifyingGlass size={36} weight="light" />
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
export function ErrorBox({ error, retry }) {
  return (
    <div className="error-box" role="alert">
      <WarningCircle size={21} />
      <div>
        <strong>{error.message || "加载失败"}</strong>
        {error.traceId && <small>请求编号：{error.traceId}</small>}
      </div>
      {retry && (
        <button className="button secondary" onClick={retry}>
          重试
        </button>
      )}
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading">
      <CircleNotch size={25} className="spin" />
      正在加载…
    </div>
  );
}
export function StatCard({
  icon: Icon,
  color,
  label,
  value,
  unit,
  trend,
  note,
}) {
  return (
    <div className="stat-card">
      <div className={`stat-icon ${color}`}>
        <Icon weight="duotone" size={30} />
      </div>
      <div>
        <span className="stat-label">{label}</span>
        <div className="stat-number">
          {value}
          <small>{unit}</small>
        </div>
        <div className="stat-note">
          {note || "较上月"} <span>{trend}</span>
        </div>
      </div>
    </div>
  );
}
export function Pagination({ page, pages, total, onChange }) {
  const nums = [
    ...new Set([
      1,
      Math.max(1, page - 1),
      page,
      Math.min(pages, page + 1),
      Math.min(pages, page + 2),
      pages,
    ]),
  ].sort((a, b) => a - b);
  return (
    <div className="pagination">
      <span>共 {total.toLocaleString()} 条</span>
      <button
        aria-label="上一页"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
      >
        ‹
      </button>
      {nums.map((n, i) => (
        <span className="page-item" key={n}>
          {i > 0 && n - nums[i - 1] > 1 && <span className="ellipsis">…</span>}
          <button
            aria-label={`第${n}页`}
            aria-current={n === page ? "page" : undefined}
            className={n === page ? "active" : ""}
            onClick={() => onChange(n)}
          >
            {n}
          </button>
        </span>
      ))}
      <button
        aria-label="下一页"
        disabled={page >= pages}
        onClick={() => onChange(page + 1)}
      >
        ›
      </button>
    </div>
  );
}
export function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function exportCsv(rows, name) {
  const safeCell = (value) => {
    let s = String(value ?? "");
    if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
    return `"${s.replaceAll('"', '""')}"`;
  };
  downloadBlob(
    new Blob(
      ["\ufeff" + rows.map((row) => row.map(safeCell).join(",")).join("\r\n")],
      { type: "text/csv;charset=utf-8" },
    ),
    name,
  );
}
export function SuccessNote({ children }) {
  return (
    <div className="success-note">
      <CheckCircle size={18} weight="fill" />
      {children}
    </div>
  );
}
