import { useEffect, useState } from "react";
import { CalendarBlank, CheckCircle, Sparkle } from "@phosphor-icons/react";
import { backend } from "../api";
import { Badge, Empty, ErrorBox, Loading, Modal } from "../components";

function dateOnly(value) {
  return value ? String(value).slice(0, 10) : "日期未识别";
}

function defaultDate() {
  return new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10);
}

export function TopicSuggestionsDialog({
  orgs,
  session,
  onClose,
  onCreated,
  onManualCreate,
  onReviewMaterials,
}) {
  const [orgId, setOrgId] = useState(
    orgs.find((org) => org.org_type === "branch")?.id || orgs[0]?.id || "",
  );
  const [topics, setTopics] = useState([]);
  const [recentTopics, setRecentTopics] = useState([]);
  const [refreshed, setRefreshed] = useState(null);
  const [focusTopics, setFocusTopics] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState(null);
  const [message, setMessage] = useState("");

  async function load(nextOrg = orgId) {
    setLoading(true);
    setError(null);
    try {
      const result = await backend.topicSuggestions({
        org_unit_id: nextOrg || null,
      });
      setTopics(result.topics || []);
      setRecentTopics(result.recent_topics || []);
      setRefreshed(result.refreshed || null);
      setFocusTopics(result.focus_topics || []);
    } catch (failure) {
      setError(failure);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setMessage("");
    load();
  }, []);

  useEffect(() => {
    if (!orgId && orgs.length) {
      setOrgId(
        orgs.find((org) => org.org_type === "branch")?.id || orgs[0].id,
      );
    }
  }, [orgs, orgId]);

  async function create(topic) {
    if (!orgId) return;
    setBusy(topic.id);
    setError(null);
    try {
      const meeting = await backend.createMeeting({
        org_unit_id: orgId,
        activity_type: topic.activity_type,
        title: topic.title,
        scheduled_on: defaultDate(),
        host: session.user.name,
        participants: [],
        source_doc_ids: [],
        agenda: "",
        notice: "",
        reason: "根据最新资料推荐创建会议草稿并生成会议文书",
      });
      const next = await backend.generateAgendaFromUpdates(meeting.id, {
        expected_revision: meeting.revision,
        reason: "根据最新资料推荐创建会议草稿并生成会议文书",
        external_update_ids: topic.source_ids || [],
      });
      onCreated(next);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy("");
    }
  }

  async function feedback(topic, decision) {
    if (!orgId) return;
    setBusy(`feedback-${topic.id}-${decision}`);
    setError(null);
    setMessage("");
    try {
      await backend.topicFeedback({
        org_unit_id: orgId,
        topic: topic.title,
        activity_type: topic.activity_type,
        decision,
        source_ids: topic.source_ids || [],
      });
      if (decision === "useful") {
        setMessage("已记录为有用主题，后续推荐会优先保留同类方向。");
      } else {
        await load(orgId);
        setMessage(
          decision === "done"
            ? "已标记为已开展，后续不再重复推荐该主题。"
            : "已记录为不相关，后续不再优先推荐该主题。",
        );
      }
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy("");
    }
  }

  return (
    <Modal
      title="推荐会议主题"
      wide
      flat
      onClose={() => !busy && onClose()}
    >
      <p className="inline-note">
        系统会先检查最新官方资料，再推荐紧跟实时的会议主题。推荐只是草稿，选中后仍需人工确认日期、主持人、参会人员并保存。
      </p>
      <div className="table-toolbar">
        <label className="inline-field">
          <span>拟办组织</span>
          <select
            value={orgId}
            onChange={(event) => {
              setOrgId(event.target.value);
              load(event.target.value);
            }}
            disabled={Boolean(busy)}
          >
            {orgs.map((org) => (
              <option key={org.id} value={org.id}>
                {org.name}
              </option>
            ))}
          </select>
        </label>
        <span className="toolbar-spacer" />
        <button
          type="button"
          className="button secondary"
          disabled={loading || Boolean(busy)}
          onClick={() => load(orgId)}
        >
          <Sparkle size={16} />
          {loading ? "正在推荐…" : "重新推荐"}
        </button>
      </div>
      {focusTopics.length > 0 && (
        <p className="inline-note">
          已按本校资料关注方向筛选：{focusTopics.join("、")}。关注方向由院系或学校管理员在“最新资料”中维护。
        </p>
      )}
      {refreshed && (
        <p className="inline-note">
          已自动检查最新资料：新增 {refreshed.added} 条，跳过重复{" "}
          {refreshed.skipped} 条，按关注方向筛选掉 {refreshed.filtered || 0} 条。
          {refreshed.errors?.length
            ? `部分来源暂时不可用：${refreshed.errors.map((item) => item.source).join("、")}`
            : ""}
        </p>
      )}
      {error && <ErrorBox error={error} />}
      {message && <p className="inline-note">{message}</p>}
      {loading ? (
        <Loading />
      ) : topics.length ? (
        <div className="topic-suggestion-list">
          {topics.map((topic) => (
            <article className="topic-suggestion-card" key={topic.id}>
              <div className="topic-suggestion-heading">
                <div>
                  <h3>{topic.title}</h3>
                  <p>{topic.reason}</p>
                </div>
                <Badge tone="blue">{topic.activity_type_label}</Badge>
              </div>
              <div className="topic-suggestion-meta">
                <span>
                  <CalendarBlank size={15} /> {topic.urgency}
                </span>
                <span>建议日期：{defaultDate()}</span>
              </div>
              <div className="topic-suggestion-sources">
                {topic.sources.map((source) => (
                  <a
                    key={source.id}
                    href={source.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {source.title}（{source.source_name} · {dateOnly(source.published_at)}）
                  </a>
                ))}
              </div>
              <div className="topic-feedback-actions">
                <button
                  type="button"
                  className="text-button"
                  disabled={Boolean(busy)}
                  onClick={() => feedback(topic, "useful")}
                >
                  {busy === `feedback-${topic.id}-useful` ? "记录中…" : "有用"}
                </button>
                <button
                  type="button"
                  className="text-button"
                  disabled={Boolean(busy)}
                  onClick={() => feedback(topic, "not_relevant")}
                >
                  {busy === `feedback-${topic.id}-not_relevant`
                    ? "记录中…"
                    : "不相关"}
                </button>
                <button
                  type="button"
                  className="text-button"
                  disabled={Boolean(busy)}
                  onClick={() => feedback(topic, "done")}
                >
                  {busy === `feedback-${topic.id}-done` ? "记录中…" : "已开展"}
                </button>
              </div>
              <div className="modal-actions">
                <button
                  type="button"
                  className="button primary"
                  disabled={Boolean(busy)}
                  onClick={() => create(topic)}
                >
                  <CheckCircle size={16} />
                  {busy === topic.id ? "正在创建…" : "用此主题创建会议"}
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="topic-empty-state">
          <Empty
            title="暂无新的推荐主题"
            description="系统不会重复推荐最近已开展的主题，也不会为凑数量生成主题。可以手动新建会议，或先补充、审核最新资料。"
          />
          <div className="topic-empty-actions">
            {onManualCreate && (
              <button
                type="button"
                className="button primary"
                onClick={onManualCreate}
              >
                手动新建会议
              </button>
            )}
            {onReviewMaterials && (
              <button
                type="button"
                className="button secondary"
                onClick={onReviewMaterials}
              >
                去审核最新资料
              </button>
            )}
          </div>
          {recentTopics.length > 0 && (
            <div className="topic-recent-topics">
              <h4>近期已开展主题</h4>
              <ul>
                {recentTopics.map((item) => (
                  <li key={`${item.title}-${item.held_on || ""}`}>
                    <strong>{item.title}</strong>
                    <span>
                      {item.activity_type_label || "组织生活"}
                      {item.held_on
                        ? ` · ${String(item.held_on).slice(0, 10)}`
                        : ""}
                    </span>
                  </li>
                ))}
              </ul>
              <p>为避免重复，这些主题暂不放入新的推荐；如确需再次开展，可手动新建会议。</p>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
