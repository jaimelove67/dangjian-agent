"""原始文件留存与读取：本地目录按租户/文档/版本隔离，SHA256 作完整性标识。

存储根目录可用环境变量 ``FILE_STORAGE_DIR`` 覆盖（测试指向临时目录），
默认相对应用工作目录的 ``uploads/``。存储不可用时入库业务不受阻，
但下载接口会明确提示原文未留存。
"""

import hashlib
import os
from pathlib import Path
from typing import Any


def validate_identifier(value: str) -> None:
    """拒绝可改变目录或文件名解释的标识，保持租户与版本路径隔离。"""
    if not value or value in (".", "..") or any(char in value for char in "/\\:\x00<>|?*"):
        raise ValueError("文件标识不能包含路径分隔符或特殊文件名字符")


def original_path(tenant_id: str, doc_id: str, revision: int) -> Path:
    """仅构造当前租户原件目录内的版本路径。"""
    validate_identifier(tenant_id)
    validate_identifier(doc_id)
    if revision < 1:
        raise ValueError("文件版本必须大于零")
    root = storage_root()
    tenant_root = root / tenant_id / "originals"
    path = tenant_root / f"{doc_id}__v{revision}.bin"
    if tenant_root.resolve() != tenant_root or path.resolve() != path:
        raise ValueError("原件存储路径不能经过符号链接")
    return path


def storage_root() -> Path:
    return Path(os.getenv("FILE_STORAGE_DIR") or "uploads").resolve()


def save_original(
    tenant_id: str,
    doc_id: str,
    revision: int,
    content: bytes,
    file_name: str,
) -> dict[str, Any]:
    """写入原始文件并返回版本快照；同版本同内容重复写入幂等。"""
    path = original_path(tenant_id, doc_id, revision)
    digest = hashlib.sha256(content).hexdigest()
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
        return {
            "path": str(path.relative_to(storage_root())),
            "sha256": digest,
            "revision": revision,
            "file_name": file_name,
            "size": len(content),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "path": str(path.relative_to(storage_root())),
        "sha256": digest,
        "revision": revision,
        "file_name": file_name,
        "size": len(content),
    }


def read_original(tenant_id: str, doc_id: str, revision: int) -> bytes | None:
    """按文档与版本读取原始文件；不存在返回 None。"""
    path = original_path(tenant_id, doc_id, revision)
    return path.read_bytes() if path.exists() else None
