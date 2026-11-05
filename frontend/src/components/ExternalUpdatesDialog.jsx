import { useEffect, useState } from "react";
import { ArrowSquareOut, ArrowsClockwise, CheckCircle, XCircle } from "@phosphor-icons/react";
import { backend } from "../api";
import { Badge, Empty, ErrorBox, Loading, Modal } from "../components";

const STATUS = {
  pending: { label: "待审核", tone: "orange" },
  approved: { label: "已采用", tone: "green" },
  rejected: { label: "不采用", tone: "gray" },
};

function dateOnly(value) {
  return value ? String(value).slice(0, 10) : "日期未识别";
}

export function ExternalUpdatesDialog({ onClose }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState(null);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState("");
  const [focus, setFocus] = useState({ topics: [], available: [] });
  const [focusSaving, setFocusSaving] = useState(false);
  const [selected, setSelected] = useState([]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [result, preferences] = await Promise.all([
        backend.externalUpdates(),
        backend.externalPreferences(),
      ]);
      setItems(result.items || []);
      setFocus(preferences || { topics: [], available: [] });
      setSelected([]);
    } catch (failure) {
      setError(failure);
    } finally {
      setLoading(false);
    }
  }

  function toggleFocus(topic) {
    setFocus((current) => ({
      ...current,
      topics: current.topics.includes(topic)
        ? current.topics.filter((item) => item !== topic)
        : [...current.topics, topic],
    }));
  }

  async function saveFocus() {
    setFocusSaving(true);
    setError(null);
    setMessage("");
    try {
      const result = await backend.updateExternalPreferences({
        topics: focus.topics,
      });
      setFocus(result);
      setMessage(
        result.topics?.length
          ? "已保存本校资料关注方向，下次抓取和推荐将按该范围筛选。"
          : "已清空关注方向，后续抓取和推荐不再按方向筛选。",
      );
    } catch (failure) {
      setError(failure);
    } finally {
      setFocusSaving(false);
    }
  }

  const pendingItems = items.filter((item) => item.status === "pending");

  function toggleSelected(id) {
    setSelected((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    );
  }

  function toggleAllSelected() {
    setSelected((current) =>
      current.length === pendingItems.length
        ? []
        : pendingItems.map((item) => item.id),
    );
  }

  async function batchReview(decision) {
    if (!selected.length) return;
    setBusy(`batch-${decision}`);
    setError(null);
    setMessage("");
    try {
      const result = await backend.batchReviewExternalUpdates({
        ids: selected,
        decision,
        note: note.trim(),
      });
      await load();
      setMessage(
        `已批量${decision === "approve" ? "采用" : "标记不采用"} ${result.count} 条资料。`,
      );
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy("");
    }
  }

  useEffect(() => {
    setMessage("");
    setNote("");
    load();
  }, []);

  async function refresh() {
    setBusy("fetch");
    setError(null);
    setMessage("");
    try {
      const result = await backend.fetchExternalUpdates();
      await load();
      const errors = result.errors?.length
        ? `；${result.errors.map((item) => `${item.source}：${item.message}`).join("；")}`
        : "";
      const focusNote = result.focus_topics?.length
        ? `，按本校关注方向筛选掉 ${result.filtered || 0} 条`
        : "";
      setMessage(
        `已抓取 ${result.sources} 个来源，新增 ${result.added} 条，跳过重复 ${result.skipped} 条${focusNote}${errors}`,
      );
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy("");
    }
  }

  async function review(item, decision) {
    setBusy(item.id);
    setError(null);
    setMessage("");
    try {
      await backend.reviewExternalUpdate(item.id, {
        decision,
        note: note.trim(),
      });
      await load();
      setMessage(
        decision === "approve"
          ? "已审核采用，并写入三会一课参考资料。"
          : "已标记不采用，不会进入会议参考资料。",
      );
      setNote("");
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy("");
    }
  }

  return (
    <Modal
      title="最新党建资料"
      wide
      flat
      onClose={() => !busy && onClose()}
    >
      <p className="inline-note">
        只从共产党员网、求是网等白名单官方来源抓取公开资料。资料先审核，审核通过后才作为三会一课议程草稿的参考；不会自动生成会议记录、参会人员或表决结果。
      </p>
      <details className="external-focus-settings">
        <summary>
          本校资料关注方向：
          {focus.topics.length ? focus.topics.join("、") : "全部方向"}
        </summary>
        <div className="external-focus-options">
          {focus.available.map((topic) => (
            <label key={topic}>
              <input
                type="checkbox"
                checked={focus.topics.includes(topic)}
                disabled={focusSaving || Boolean(busy)}
                onChange={() => toggleFocus(topic)}
              />
              {topic}
            </label>
          ))}
        </div>
        <div className="external-focus-actions">
          <span className="muted">
            不选择任何方向时，抓取和推荐不按方向筛选；已抓取资料仍需人工审核。
          </span>
          <button
            type="button"
            className="button secondary"
            disabled={focusSaving || Boolean(busy) || !focus.available.length}
            onClick={saveFocus}
          >
            {focusSaving ? "正在保存…" : "保存关注方向"}
          </button>
        </div>
      </details>
      <div className="table-toolbar">
        <button
          className="button primary"
          type="button"
          disabled={Boolean(busy)}
          onClick={refresh}
        >
          <ArrowsClockwise size={17} />
          {busy === "fetch" ? "正在抓取…" : "抓取最新资料"}
        </button>
        <span className="toolbar-spacer" />
        <span className="muted">已选 {selected.length} 条</span>
        <button
          className="button secondary"
          type="button"
          disabled={Boolean(busy) || !selected.length}
          onClick={() => batchReview("reject")}
        >
          {busy === "batch-reject" ? "处理中…" : "批量不采用"}
        </button>
        <button
          className="button secondary"
          type="button"
          disabled={Boolean(busy) || !selected.length}
          onClick={() => batchReview("approve")}
        >
          {busy === "batch-approve" ? "处理中…" : "批量采用"}
        </button>
      </div>
      <p className="inline-note">仅抓取公开页面，不执行登录或绕过访问控制。</p>
      {error && <ErrorBox error={error} retry={load} />}
      {message && <p className="inline-note">{message}</p>}
      <div className="form-grid">
        <label className="field full">
          <span>审核意见（可选）</span>
          <input
            value={note}
            onChange={(event) => setNote(event.target.value)}
            maxLength={2000}
            placeholder="例如：来源和日期已核对，可用于本月党课学习"
          />
        </label>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>
                <input
                  type="checkbox"
                  aria-label="全选待审核资料"
                  checked={
                    pendingItems.length > 0 &&
                    selected.length === pendingItems.length
                  }
                  disabled={Boolean(busy) || !pendingItems.length}
                  onChange={toggleAllSelected}
                />
              </th>
              <th>标题 / 来源</th>
              <th>发布日期</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const status = STATUS[item.status] || {
                label: item.status,
                tone: "gray",
              };
              return (
                <tr key={item.id}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`选择${item.title}`}
                      checked={selected.includes(item.id)}
                      disabled={Boolean(busy) || item.status !== "pending"}
                      onChange={() => toggleSelected(item.id)}
                    />
                  </td>
                  <td>
                    <a
                      href={item.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-button link"
                    >
                      {item.title} <ArrowSquareOut size={14} />
                    </a>
                    <small className="cell-subtext">
                      {item.source_name} · {dateOnly(item.published_at)} · 抓取于{" "}
                      {dateOnly(item.fetched_at)}
                    </small>
                    {item.summary && (
                      <small className="cell-subtext">
                        {item.summary.slice(0, 220)}
                        {item.summary.length > 220 ? "…" : ""}
                      </small>
                    )}
                    {item.review_note && (
                      <small className="cell-subtext">
                        审核意见：{item.review_note}
                      </small>
                    )}
                  </td>
                  <td>{dateOnly(item.published_at)}</td>
                  <td>
                    <Badge tone={status.tone}>{status.label}</Badge>
                  </td>
                  <td>
                    {item.status === "pending" ? (
                      <div className="identity-row-actions">
                        <button
                          type="button"
                          className="text-button link"
                          disabled={Boolean(busy)}
                          onClick={() => review(item, "approve")}
                        >
                          <CheckCircle size={15} />
                          审核采用
                        </button>
                        <button
                          type="button"
                          className="text-button link"
                          disabled={Boolean(busy)}
                          onClick={() => review(item, "reject")}
                        >
                          <XCircle size={15} />
                          不采用
                        </button>
                      </div>
                    ) : (
                      <span className="muted">已处理</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {loading && <Loading />}
        {!items.length && !loading && (
          <Empty
            title="暂无外部资料"
            description="点击“抓取最新资料”从官方来源获取，或稍后重试。"
          />
        )}
      </div>
    </Modal>
  );
}
