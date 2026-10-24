"""字段级敏感分级与第三人信息脱敏单元测试（T-MEM-12 / SEC-01、SEC-04）。

覆盖：材料 / 评议 / 投票密级来源与简称归一、密级比较、出网与向量化口径、
按等级脱敏（含嵌套 procedure 与留痕快照）、脱敏占位不当内容写回、批量导出口径，
以及"第三人身份字段不被采集"的入口守卫。
"""

import json
from types import SimpleNamespace

import pytest

from app.core.constants import DataLevel
from app.main import app
from app.models.user import UserRole
from app.rules import data_sensitivity as ds

CONFIG = ds.DEFAULT_CONFIG_PATH


def test_shipped_config_levels_and_labels():
    rules = ds.load_rules(CONFIG)
    assert ds.material_level("政治审查材料", rules=rules) is DataLevel.CLASSIFIED
    assert ds.material_level("群众评议材料", rules=rules) is DataLevel.SENSITIVE
    assert ds.material_level("入党申请书", rules=rules) is DataLevel.INTERNAL
    assert rules.review_level is DataLevel.SENSITIVE
    assert rules.vote_level is DataLevel.SENSITIVE
    # 选优结论与团组织推优台账同一口径：都含"组织对某人的评价"
    assert rules.selection_level is DataLevel.SENSITIVE
    assert ds.selection_level(rules=rules) is DataLevel.SENSITIVE


def test_short_names_cannot_dodge_the_level():
    for short in ("政审材料", "政治审查", "　政治审查材料　"):
        assert ds.material_level(short) is DataLevel.CLASSIFIED
    assert ds.material_level("群众评议") is DataLevel.SENSITIVE


def test_unknown_or_empty_material_type_is_internal():
    assert ds.material_level("某个没见过的材料") is DataLevel.INTERNAL
    assert ds.material_level("") is DataLevel.INTERNAL
    assert ds.material_level(None) is DataLevel.INTERNAL


def test_missing_config_falls_back_conservatively(tmp_path):
    rules = ds.load_rules(str(tmp_path / "missing.yaml"))
    # 配置读不到时不是"什么都放行"：政审仍按涉密、群众评议仍按敏感
    assert ds.material_level("政治审查材料", rules=rules) is DataLevel.CLASSIFIED
    assert ds.material_level("政审材料", rules=rules) is DataLevel.CLASSIFIED


def test_config_can_raise_a_level(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text(
        "data_sensitivity:\n"
        "  member_material_levels:\n"
        "    入党申请书: classified\n"
        "  member_review_level: classified\n"
        "  member_selection_level: classified\n",
        encoding="utf-8",
    )
    rules = ds.load_rules(str(path))
    assert ds.material_level("入党申请书", rules=rules) is DataLevel.CLASSIFIED
    assert rules.review_level is DataLevel.CLASSIFIED
    assert rules.selection_level is DataLevel.CLASSIFIED
    # 未列出的类型仍按 internal（不因为改了一项就把所有材料抬高）
    assert ds.material_level("思想汇报", rules=rules) is DataLevel.INTERNAL


def test_broken_config_falls_back_to_defaults(tmp_path):
    path = tmp_path / "rules.yaml"
    path.write_text("data_sensitivity: [这不是映射]\n", encoding="utf-8")
    rules = ds.load_rules(str(path))
    assert ds.material_level("政治审查材料", rules=rules) is DataLevel.CLASSIFIED
    # 配置损坏时选优口径不许变松：仍按敏感（不是"读不到就放行"）
    assert rules.selection_level is DataLevel.SENSITIVE


def test_level_ordering_and_guards():
    assert ds.level_rank(DataLevel.PUBLIC) < ds.level_rank(DataLevel.INTERNAL)
    assert ds.level_rank(DataLevel.INTERNAL) < ds.level_rank(DataLevel.SENSITIVE)
    assert ds.level_rank(DataLevel.SENSITIVE) < ds.level_rank(DataLevel.CLASSIFIED)
    assert ds.level_at_least(DataLevel.SENSITIVE, DataLevel.INTERNAL)
    assert not ds.level_at_least(DataLevel.INTERNAL, DataLevel.SENSITIVE)
    assert ds.level_label(DataLevel.CLASSIFIED) == "涉密"
    assert ds.cloud_allowed(DataLevel.INTERNAL) and not ds.cloud_allowed(DataLevel.SENSITIVE)
    assert not ds.cloud_allowed(DataLevel.CLASSIFIED)
    # 涉密不入向量库；敏感仍可进入（但不出网，由 cloud_allowed 管）
    assert ds.embedding_allowed(DataLevel.SENSITIVE)
    assert not ds.embedding_allowed(DataLevel.CLASSIFIED)


def test_annotate_level_shape():
    assert ds.annotate_level(DataLevel.CLASSIFIED) == {
        "data_level": "classified",
        "data_level_label": "涉密",
        "cloud_allowed": False,
        "embedding_allowed": False,
    }


@pytest.mark.parametrize(
    "role,expected",
    [
        (UserRole.SYSTEM_ADMIN, DataLevel.SENSITIVE),
        (UserRole.BRANCH_SECRETARY, DataLevel.SENSITIVE),
        (UserRole.MEMBER, DataLevel.INTERNAL),
        (UserRole.APPLICANT, DataLevel.PUBLIC),
    ],
)
def test_viewer_level_from_role(role, expected):
    assert ds.viewer_level(SimpleNamespace(role=role)) is expected


def test_viewer_level_without_role_is_public():
    assert ds.viewer_level(SimpleNamespace(role=None)) is DataLevel.PUBLIC


def test_same_or_higher_level_keeps_text():
    payload = {"note": "经向其舅舅核实", "description": "说明"}
    data, redacted = ds.redact_third_party(
        payload, level=DataLevel.SENSITIVE, viewer=DataLevel.SENSITIVE
    )
    assert data == payload and redacted == []


def test_lower_level_viewer_loses_third_party_text():
    payload = {"note": "经向其舅舅王某某核实", "description": "说明", "material_type": "群众评议材料"}
    data, redacted = ds.redact_third_party(
        payload, level=DataLevel.SENSITIVE, viewer=DataLevel.INTERNAL
    )
    assert data["note"] == ds.REDACTED_NOTE
    assert data["description"] == ds.REDACTED_NOTE
    assert data["material_type"] == "群众评议材料"
    assert redacted == ["description", "note"]


def test_classified_uses_the_classified_placeholder():
    data, redacted = ds.redact_third_party(
        {"note": "政审谈话记录"}, level=DataLevel.CLASSIFIED, viewer=DataLevel.SENSITIVE
    )
    assert data["note"] == ds.CLASSIFIED_NOTE
    assert redacted == ["note"]


def test_empty_fields_are_not_counted_as_redacted():
    data, redacted = ds.redact_third_party(
        {"note": "   "}, level=DataLevel.CLASSIFIED, viewer=DataLevel.INTERNAL
    )
    assert data["note"] == "   " and redacted == []


def test_nested_procedure_and_history_are_redacted():
    payload = {
        "procedure": {"self_assessment": "自评", "peer_review": "张三说他不积极"},
        "review_history": [{"revision": 1, "note": "审核备注"}],
    }
    data, redacted = ds.redact_third_party(
        payload, level=DataLevel.SENSITIVE, viewer=DataLevel.INTERNAL
    )
    assert data["procedure"]["peer_review"] == ds.REDACTED_NOTE
    assert data["procedure"]["self_assessment"] == "自评"
    assert data["review_history"][0]["note"] == ds.REDACTED_NOTE
    assert redacted == ["procedure.peer_review", "review_history.note"]


def test_export_never_carries_third_party_fields():
    row = {
        "name": "合成党员",
        "note": "经向其舅舅核实",
        "description": "说明",
        "comment": "投票意见",
        "peer_review": "互评",
        "decide_note": "上级批复说明",
        # 嵌套层同样不写出（导出件里连"这里本来有内容"的占位都不该有）
        "procedure": {"self_assessment": "自评", "peer_review": "张三说他不积极"},
        "review_history": [{"revision": 1, "note": "审核备注"}],
    }
    stripped = ds.strip_third_party_fields(row)
    assert set(stripped) == {"name", "decide_note", "procedure", "review_history"}
    assert stripped["procedure"] == {"self_assessment": "自评"}
    assert stripped["review_history"] == [{"revision": 1}]
    dumped = json.dumps(stripped, ensure_ascii=False)
    for marker in ("经向其舅舅核实", "投票意见", "张三说他不积极", "审核备注"):
        assert marker not in dumped


def test_placeholder_is_not_content():
    assert ds.is_redaction_placeholder(ds.REDACTED_NOTE)
    assert ds.is_redaction_placeholder(f"  {ds.CLASSIFIED_NOTE} ")
    assert not ds.is_redaction_placeholder("经向其舅舅核实")
    assert not ds.is_redaction_placeholder("")
    assert not ds.is_redaction_placeholder(None)


def test_no_request_schema_collects_third_party_identity():
    """入口不采集第三人身份字段（T-MEM-14 / T-MEM-11 的边界）；加了就要先改这里。"""
    properties: set[str] = set()
    for schema in app.openapi().get("components", {}).get("schemas", {}).values():
        properties.update((schema.get("properties") or {}).keys())
    assert properties, "OpenAPI 里没有读到任何请求字段"
    assert ds.IDENTITY_FIELDS & properties == set()


def test_vote_identity_is_an_identity_field_not_a_content_field():
    """投票人身份按"身份字段"处理（不采集 / 不返回），不是可以"脱敏后照发"的自由文本。"""
    assert "voter_id" in ds.IDENTITY_FIELDS
    assert "voter_id" not in ds.THIRD_PARTY_FIELDS
    assert ds.THIRD_PARTY_FIELDS == {"note", "description", "comment", "peer_review"}
