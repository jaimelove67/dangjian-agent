"""保留期现状报告（T-SEC-07）：把治理页填写的保留天数变成可核对的数字。

这里只测纯文件扫描（不依赖数据库，库内计数由集成测试覆盖）：核心口径是
**文件保留天数只用于已软删除条目的原件**——在用条目的原件按年龄报"到期"会
诱导管理员删掉仍在执行的制度文件，所以必须钉住"不报"这件事。
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.retention_service import FILE_SCAN_LIMIT, scan_storage

TENANT = "tenant-a"
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")


def _write(root: Path, relative: str, *, days_ago: float) -> Path:
    """按"多少天以前"写一个占位文件：内容无关，只测分类与年龄"""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"sealed")
    moment = (NOW - timedelta(days=days_ago)).timestamp()
    os.utime(path, (moment, moment))
    return path


def _scan(root: Path | None, deleted: set[str], *, file_days: int = 365, limit: int = FILE_SCAN_LIMIT):
    return scan_storage(
        root, TENANT, deleted_doc_ids=deleted, file_days=file_days, now=NOW, limit=limit
    )


def test_deleted_document_original_is_counted_and_aged(tmp_path: Path):
    _write(tmp_path, f"{TENANT}/originals/doc-gone__v1.bin", days_ago=500)
    _write(tmp_path, f"{TENANT}/originals/doc-gone__v2__h{'a' * 64}.bin", days_ago=10)
    _write(tmp_path, f"{TENANT}/originals/doc-live__v1.bin", days_ago=500)

    result = _scan(tmp_path, {"doc-gone"})

    assert result["total"] == 3
    assert result["deleted_docs_total"] == 2
    # 只有 500 天前那个版本超过保留期；10 天前那个还没到期
    assert result["deleted_docs_expired"] == 1
    assert result["truncated"] is False
    assert result["unreadable"] == 0
    assert STAMP.match(result["oldest"]) and STAMP.match(result["newest"])


def test_live_document_original_is_never_reported_as_expired(tmp_path: Path):
    """在用条目的原件不参与保留期核对：长期有效的制度文件不会被报成"到期" """
    _write(tmp_path, f"{TENANT}/originals/doc-live__v1.bin", days_ago=3000)

    result = _scan(tmp_path, set())

    assert result["total"] == 1
    assert result["deleted_docs_total"] == 0
    assert result["deleted_docs_expired"] == 0


def test_retention_boundary_is_exclusive_at_exactly_file_days(tmp_path: Path):
    """恰好到保留期当天不算"已超过"：边界写成 <= 会让管理员每年多清一天的数据"""
    _write(tmp_path, f"{TENANT}/originals/doc-gone__v1.bin", days_ago=365)
    _write(tmp_path, f"{TENANT}/originals/doc-gone__v2.bin", days_ago=365.5)

    result = _scan(tmp_path, {"doc-gone"})

    assert result["deleted_docs_total"] == 2
    assert result["deleted_docs_expired"] == 1


def test_archive_snapshots_and_unknown_files_are_not_matched_to_deleted_records(tmp_path: Path):
    """归档快照按业务编号哈希命名，判不出归属；判不出就不参与核对，只计入总数"""
    _write(tmp_path, f"{TENANT}/originals/archive-{'b' * 32}__v1.bin", days_ago=900)
    _write(tmp_path, f"{TENANT}/originals/weird.txt", days_ago=900)
    _write(tmp_path, f"{TENANT}/originals/doc-gone__v0.bin", days_ago=900)
    _write(tmp_path, f"{TENANT}/other/doc-gone__v1.bin", days_ago=900)

    result = _scan(tmp_path, {"doc-gone"})

    kinds = {row["kind"]: row["total"] for row in result["by_kind"]}
    assert kinds["originals"] == 0
    assert kinds["archives"] == 1
    assert kinds["other"] == 3
    assert result["total"] == 4
    assert result["deleted_docs_total"] == 0


def test_other_tenants_and_missing_roots_are_not_counted(tmp_path: Path):
    _write(tmp_path, "tenant-b/originals/doc-gone__v1.bin", days_ago=900)

    result = _scan(tmp_path, {"doc-gone"})

    assert result["total"] == 0 and result["scanned"] == 0
    # 没有存储目录（新装环境 / 未落盘）时按空报告处理，不抛异常也不编数字
    empty = _scan(tmp_path / "missing", {"doc-gone"})
    assert empty["total"] == 0 and empty["by_kind"][0]["total"] == 0
    assert _scan(None, {"doc-gone"})["total"] == 0


def test_scan_reports_truncation_instead_of_pretending_it_finished(tmp_path: Path):
    for index in range(3):
        _write(tmp_path, f"{TENANT}/originals/doc-{index}__v1.bin", days_ago=30)

    result = _scan(tmp_path, set(), limit=2)

    assert result["scanned"] == 2
    assert result["truncated"] is True
    assert result["by_kind"][0]["kind"] == "originals"
