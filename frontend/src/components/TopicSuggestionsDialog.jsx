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
}) {
  const [orgId, setOrgId] = useState(
    orgs.find((org) => org.org_type === "branch")?.id || orgs[0]?.id || "",
  );
  const [topics, setTopics] = useState([]);
  const [refreshed, setRefreshed] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState(null);

  async function load(nextOrg = orgId) {
    setLoading(true);
    setError(null);
    try {
      const result = await backend.topicSuggestions({
        org_unit_id: nextOrg || null,
      });
      setTopics(result.topics || []);
      setRefreshed(result.refreshed || null);
    } catch (failure) {
      setError(failure);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
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
        reason: "根据最新资料推荐创建会议草稿",
      });
      const next = await backend.generateAgendaFromUpdates(meeting.id, {
        expected_revision: meeting.revision,
        reason: "根据最新资料推荐创建会议草稿",
        external_update_ids: topic.source_ids || [],
      });
      onCreated(next);
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
      {refreshed && (
        <p className="inline-note">
          已自动检查最新资料：新增 {refreshed.added} 条，跳过重复{" "}
          {refreshed.skipped} 条。
          {refreshed.errors?.length
            ? `部分来源暂时不可用：${refreshed.errors.map((item) => item.source).join("、")}`
            : ""}
        </p>
      )}
      {error && <ErrorBox error={error} />}
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
        <Empty
          title="暂无合适的推荐主题"
          description="可能还没有已审核的最新资料，或最近已开过相同主题。可以先抓取并审核资料，或稍后重新推荐。"
        />
      )}
    </Modal>
  );
}
