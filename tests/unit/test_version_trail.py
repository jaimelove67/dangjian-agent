"""版本留痕单元测试（T-SEC-11：提示词版本折算、口径说明与行映射）。

不连库：查询构造只断言生成的 SQL 条件，提示词历史用配置版本对象直接折算。
权限与租户边界在接口层，另有 HTTP 集成用例。
"""
from datetime import datetime
from types import SimpleNamespace

from app.core.versions import prompt_versions, version_fingerprint, workflow_versions
from app.services.version_trail_service import (
    KNOWLEDGE_EVENTS,
    PROMPT_DEFAULTS,
    UNKNOWN_ACTOR,
    KnowledgeRevisionRow,
    build_knowledge_revision_query,
    effective_prompt_versions,
    knowledge_scope_note,
    prompt_changes,
    prompt_scope_note,
)


def _revision(version=1, actor_id="u1", reason="调整提示词", **values):
    return SimpleNamespace(
        version=version,
        actor_id=actor_id,
        reason=reason,
        values=values,
        created_at=datetime(2026, 3, version, 2, 0),
    )


def _names(mapping):
    return {key: (value, value + "-login") for key, value in mapping.items()}


def _params(stmt) -> dict:
    return stmt.compile().params


class TestPromptVersions:
    def test_defaults_when_nothing_is_configured(self):
        assert effective_prompt_versions(None) == dict(PROMPT_DEFAULTS)
        assert effective_prompt_versions({}) == dict(PROMPT_DEFAULTS)

    def test_configured_value_wins_and_missing_kind_falls_back(self):
        effective = effective_prompt_versions({"prompt_versions": {"qa": "v2"}})
        assert effective["qa"] == "v2"
        # 只配了 qa：rewrite 回落默认，而不是留空——空字符串会被当成"没留痕"
        assert effective["rewrite"] == PROMPT_DEFAULTS["rewrite"]

    def test_fingerprint_covers_prompt_and_workflow(self):
        fingerprint = version_fingerprint(None)
        assert set(fingerprint) == {"prompt", "workflow"}
        assert set(fingerprint["prompt"]) == set(PROMPT_DEFAULTS)
        # 工作流版本就是契约常量本身，不在这里另写一遍
        assert set(fingerprint["workflow"]) == {item["workflow"] for item in workflow_versions()}
        assert all(
            fingerprint["workflow"][item["workflow"]] == item["version"]
            for item in workflow_versions()
        )

    def test_prompt_versions_reads_tenant_config_cache(self):
        """生效版本必须走租户配置（缓存），不能只看默认值"""
        from app.core.config import tenant_config

        tenant_config._cache["t-ver"] = {"prompt_versions": {"qa": "v2", "rewrite": "v2"}}
        try:
            assert prompt_versions("t-ver") == {"qa": "v2", "rewrite": "v2"}
        finally:
            tenant_config._cache.pop("t-ver", None)


class TestPromptHistory:
    def test_first_revision_is_registered_as_initial_value(self):
        entries = prompt_changes([_revision(1)], _names({"u1": "张三"}))
        assert len(entries) == 1
        assert entries[0].config_version == 1
        assert entries[0].actor == "张三"
        # 首次登记：每个提示词都从"未设置"变成当时的取值，这本身就是留痕
        assert [change.kind for change in entries[0].changes] == list(PROMPT_DEFAULTS)
        assert all(change.before is None for change in entries[0].changes)
        assert {change.kind: change.after for change in entries[0].changes} == dict(PROMPT_DEFAULTS)

    def test_only_revisions_that_change_a_prompt_are_listed(self):
        rows = [
            _revision(1, prompt_versions={"qa": "v1"}),
            # 第二次提交只改了别的字段：不该出现在提示词版本历史里
            _revision(2, prompt_versions={"qa": "v1"}, model_routes={"llm": "m1"}),
            _revision(3, prompt_versions={"qa": "v2"}),
        ]
        entries = prompt_changes(rows, _names({"u1": "张三"}))
        assert [entry.config_version for entry in entries] == [1, 3]
        changes = entries[-1].changes
        assert len(changes) == 1
        assert (changes[0].kind, changes[0].before, changes[0].after) == ("qa", "v1", "v2")

    def test_clearing_a_prompt_returns_to_default_and_is_visible(self):
        rows = [
            _revision(1, prompt_versions={"qa": "v2"}),
            _revision(2, prompt_versions={}),
        ]
        entries = prompt_changes(rows, {})
        assert entries[-1].prompt_versions["qa"] == PROMPT_DEFAULTS["qa"]
        cleared = entries[-1].changes[0]
        assert (cleared.kind, cleared.before, cleared.after) == (
            "qa",
            "v2",
            PROMPT_DEFAULTS["qa"],
        )

    def test_actor_falls_back_to_username_then_placeholder(self):
        rows = [_revision(1), _revision(2)]
        entries = prompt_changes(rows, {"u1": ("", "zhangsan")})
        assert entries[0].actor == "zhangsan"
        assert entries[0].username == "zhangsan"
        missing = prompt_changes([_revision(1)], {})
        assert missing[0].actor == UNKNOWN_ACTOR

    def test_changed_at_stays_utc_naive_for_the_shared_time_converter(self):
        """接口给原始 UTC 朴素时间，展示交给与审计 / 台账同一件钟（界面 formatDate）"""
        entry = prompt_changes([_revision(1)], {})[0]
        assert entry.changed_at == datetime(2026, 3, 1, 2, 0)
        assert entry.changed_at.tzinfo is None


class TestKnowledgeQuery:
    def test_only_version_events_of_the_tenant_are_read(self):
        stmt = build_knowledge_revision_query("t1")
        sql = str(stmt)
        assert "audit_logs.tenant_id = " in sql
        assert "audit_logs.resource_type = " in sql
        assert "audit_logs.result = " in sql
        assert "audit_logs.action IN" in sql
        # 只收录入库与内容更新；状态变更 / 元数据修正 / 下载不算版本变更
        assert set(_params(stmt)["action_1"]) == set(KNOWLEDGE_EVENTS)
        assert "ORDER BY audit_logs.created_at DESC" in sql
        # 条目与账号都是外连接：查不到也不能让这一行消失
        assert sql.count("LEFT OUTER JOIN") == 2


class TestKnowledgeRowMapping:
    def _row(self, action, new_value, old_value=None, **joined):
        audit = SimpleNamespace(
            action=action,
            new_value=new_value,
            old_value=old_value,
            created_at=datetime(2026, 3, 1, 2, 0),
            resource_id="doc-internal-1",
            user_id="u1",
        )
        return KnowledgeRevisionRow.from_row(
            (
                audit,
                joined.get("doc_id", "DOC-1"),
                joined.get("title", "某制度"),
                joined.get("name", "张三"),
                joined.get("username", "zhangsan"),
            )
        )

    def test_creation_is_the_first_revision(self):
        row = self._row("create", {"sha256": "x", "bytes": 10})
        assert (row.event_text, row.revision, row.previous_revision) == ("入库", 1, None)

    def test_content_update_carries_both_revisions(self):
        row = self._row("update_content", {"revision": 3, "sha256": "x"}, {"revision": 2})
        assert row.event_text == "内容更新"
        assert (row.previous_revision, row.revision) == (2, 3)
        assert row.doc_id == "DOC-1" and row.title == "某制度"
        assert row.actor == "张三"

    def test_unreadable_payload_leaves_revision_empty(self):
        # 审计摘要把正文哈希掉，只有 revision 是明文；取不到就不编造
        row = self._row("update_content", None, None)
        assert row.revision is None and row.previous_revision is None

    def test_deleted_document_and_actor_are_tolerated(self):
        row = self._row("create", {}, doc_id=None, title=None, name=None, username=None)
        assert row.doc_id is None and row.title is None
        assert row.actor == UNKNOWN_ACTOR

    def test_notes_name_the_tenant_and_the_limits(self):
        assert "t1" in knowledge_scope_note("t1")
        # 不把"审计里没有的东西"说成有：正文不在留痕里
        assert "不含被改动的正文" in knowledge_scope_note("t1")
        prompt_note = prompt_scope_note("t1", 2)
        assert "t1" in prompt_note and "2 次版本变更" in prompt_note
        assert "回落" in prompt_note
