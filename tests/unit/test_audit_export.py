"""审计导出单元测试（对账包组成、台账取值与口径自证）"""
import io
import json
import zipfile
from datetime import datetime

from app.core.audit import make_audit_log
from app.core.constants import AuditAction, AuditResult, DataLevel
from app.services.audit_export import (
    CSV_NAME,
    GUIDE_NAME,
    HEADERS,
    MANIFEST_NAME,
    build_audit_package,
    build_manifest,
    guide_text,
    row_values,
)


def _log(**overrides):
    log = make_audit_log(
        tenant_id="t1",
        user_id="u1",
        user_name="张三",
        action=AuditAction.EXPORT,
        resource_type="audit_log",
        request_id="req-1",
        result=AuditResult.SUCCESS,
        data_level=DataLevel.SENSITIVE,
        ip_address="10.0.0.1",
        old_value={"title": "旧"},
        new_value={"rows": 3},
    )
    log.created_at = datetime(2026, 10, 16, 2, 30)
    for key, value in overrides.items():
        setattr(log, key, value)
    return log


def _csv_lines(content: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return archive.read(CSV_NAME).decode("utf-8-sig").strip().splitlines()


class TestRowValues:
    def test_columns_match_headers_and_use_beijing_time(self):
        values = row_values(_log())
        assert len(values) == len(HEADERS)
        # 库内 02:30 UTC → 台账 10:30（北京时间），复核者不需要自己换算
        assert values[0] == "2026-10-16 10:30"
        assert values[1] == "u1"
        assert values[4] == "audit_log"
        assert values[6] == "sensitive"
        assert values[8] == "10.0.0.1"
        assert json.loads(values[11]) == {"title": "旧"}
        assert json.loads(values[12]) == {"rows": 3}

    def test_empty_json_and_missing_fields_become_blank(self):
        log = _log(old_value=None, new_value={}, resource_id=None, ip_address=None)
        values = row_values(log)
        assert values[5] == ""
        assert values[8] == ""
        assert values[11] == "" and values[12] == ""

    def test_error_message_is_exported(self):
        assert row_values(_log(error_message="权限或业务校验未通过"))[10] == "权限或业务校验未通过"


class TestManifest:
    def test_carries_scope_owner_and_count(self):
        manifest = build_manifest(
            rows=7, scope_note="租户 t1；动作 export", exported_by="管理员（admin）"
        )
        assert manifest["导出条数"] == 7
        assert manifest["筛选口径"] == "租户 t1；动作 export"
        assert manifest["导出人"] == "管理员（admin）"
        assert "北京时间" in manifest["时区"]
        assert manifest["字段"] == list(HEADERS)

    def test_blank_scope_and_owner_fall_back_to_honest_defaults(self):
        manifest = build_manifest(rows=0, scope_note="", exported_by="")
        assert manifest["筛选口径"] == "本租户全部审计记录"
        assert manifest["导出人"] == "未记录"

    def test_guide_text_renders_nested_and_list_values(self):
        text = guide_text(build_manifest(rows=2, scope_note="口径", exported_by="甲"))
        assert "导出条数：2" in text
        assert CSV_NAME in text
        assert "字段：" in text
        assert "  - 时间、用户编号" in text


class TestPackage:
    def test_zip_contains_csv_guide_and_manifest(self):
        content = build_audit_package([_log()], scope_note="租户 t1", exported_by="甲")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert set(archive.namelist()) == {CSV_NAME, GUIDE_NAME, MANIFEST_NAME}
            assert archive.read(CSV_NAME).startswith(b"\xef\xbb\xbf")
            manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
            assert manifest["导出条数"] == 1
            assert "导出条数：1" in archive.read(GUIDE_NAME).decode("utf-8")
        lines = _csv_lines(content)
        assert lines[0].split(",") == list(HEADERS)
        assert len(lines) == 2

    def test_csv_formula_injection_is_neutralised(self):
        content = build_audit_package([_log(user_name="=1+2")])
        assert "'=1+2" in _csv_lines(content)[1]

    def test_empty_result_still_produces_a_usable_package(self):
        content = build_audit_package([], scope_note="租户 t1")
        assert _csv_lines(content) == [",".join(HEADERS)]
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            assert json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))["导出条数"] == 0
