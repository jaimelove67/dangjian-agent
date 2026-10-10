"""原始文件留存与读取：本地目录按租户/文档/版本隔离，SHA256 作完整性标识。

存储根目录可用环境变量 ``FILE_STORAGE_DIR`` 覆盖（测试指向临时目录），
默认相对应用工作目录的 ``uploads/``。存储不可用时入库业务不受阻，
但下载接口会明确提示原文未留存。
"""

import hashlib
import os
from pathlib import Path
from typing import Any


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
    root = storage_root() / tenant_id / "originals"
    stored_name = f"{doc_id}__v{revision}.bin"
    path = root / stored_name
    digest = hashlib.sha256(content).hexdigest()
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
        return {
            "path": str(path.relative_to(storage_root())),
            "sha256": digest,
            "revision": revision,
            "file_name": file_name,
            "size": len(content),
        }
    root.mkdir(parents=True, exist_ok=True)
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
    path = storage_root() / tenant_id / "originals" / f"{doc_id}__v{revision}.bin"
    return path.read_bytes() if path.exists() else None


def remove_originals(tenant_id: str, doc_id: str) -> None:
    """软删除文档时清理原始文件版本。"""
    root = storage_root() / tenant_id / "originals"
    for path in root.glob(f"{doc_id}__v*.bin"):
        try:
            path.unlink()
        except OSError:
            pass
