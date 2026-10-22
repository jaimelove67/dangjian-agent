"""原件与归档的认证加密存储；授权由业务服务在读取前检查。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.encryption import MAGIC, EncryptionError, atomic_write, filesystem_path, seal, unseal


def validate_identifier(value: str) -> None:
    if not value or value in (".", "..") or any(char in value for char in "/\\:\x00<>|?*"):
        raise ValueError("文件标识不能包含路径分隔符或特殊文件名字符")


def storage_root() -> Path:
    return Path(os.getenv("FILE_STORAGE_DIR") or settings.FILE_STORAGE_DIR).absolute()


def original_path(tenant_id: str, doc_id: str, revision: int, digest: str | None = None) -> Path:
    validate_identifier(tenant_id)
    validate_identifier(doc_id)
    if revision < 1:
        raise ValueError("文件版本必须大于零")
    if digest is not None and not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("文件校验值无效")
    root = storage_root()
    name = f"{doc_id}__v{revision}" + (f"__h{digest}" if digest else "") + ".bin"
    path = root / tenant_id / "originals" / name
    if root.resolve() != root or path.parent.resolve() != path.parent or path.resolve() != path:
        raise ValueError("原件存储路径不能经过符号链接")
    return path


def file_purpose(relative: Path, *, audits: bool = False) -> str:
    """由受约束的相对路径推导 AAD；同时兼容既有原件命名。"""
    if audits:
        import uuid

        if len(relative.parts) != 1 or relative.suffix != ".audit":
            raise ValueError("审计缓冲路径无效")
        return "audit:" + str(uuid.UUID(relative.stem))
    if len(relative.parts) == 3 and relative.parts[1] == "archives":
        # 党员档案影像件：AAD 绑定租户 + 材料编号，单个文件被拷走也解不开
        tenant = relative.parts[0]
        match = re.fullmatch(r"(.+)__h([a-f0-9]{64})\.bin", relative.name)
        if match is None:
            raise ValueError("档案影像名无效")
        material_id, digest = match.groups()
        validate_identifier(tenant)
        validate_identifier(material_id)
        return f"archive:{tenant}:{material_id}:{digest}"
    if len(relative.parts) != 3 or relative.parts[1] != "originals":
        raise ValueError("原件目录结构无效")
    tenant = relative.parts[0]
    match = re.fullmatch(r"(.+)__v([1-9][0-9]*)(?:__h([a-f0-9]{64}))?\.bin", relative.name)
    if match is None:
        raise ValueError("原件版本名无效")
    doc_id, revision, digest = match.groups()
    validate_identifier(tenant)
    validate_identifier(doc_id)
    return f"original:{tenant}:{doc_id}:{revision}" + (f":{digest}" if digest else "")


def authenticated_content(raw: bytes, relative: Path, *, audits: bool = False) -> bytes:
    content = unseal(raw, file_purpose(relative, audits=audits))
    address = re.search(r"__h([a-f0-9]{64})$", relative.stem)
    if not audits and address is not None:
        digest = address[1]
        if hashlib.sha256(content).hexdigest() != digest:
            raise EncryptionError("内容寻址文件校验失败")
    return content


def save_original(
    tenant_id: str, doc_id: str, revision: int, content: bytes, file_name: str
) -> dict[str, Any]:
    """发布不可覆盖的内容寻址文件。DB 回滚的产物留存，不会阻塞不同内容的重试。"""
    digest = hashlib.sha256(content).hexdigest()
    path = original_path(tenant_id, doc_id, revision, digest)
    relative = path.relative_to(storage_root())
    filesystem_path(path.parent).mkdir(parents=True, exist_ok=True)
    encrypted = seal(content, file_purpose(relative))
    try:
        atomic_write(path, encrypted)
    except FileExistsError:
        if authenticated_content(filesystem_path(path).read_bytes(), relative) != content:
            raise EncryptionError("已发布原件完整性校验失败") from None
    return {
        "path": relative.as_posix(),
        "sha256": digest,
        "revision": revision,
        "file_name": file_name,
        "size": len(content),
    }


def read_original(
    tenant_id: str, doc_id: str, revision: int, expected_sha256: str | None = None
) -> bytes | None:
    """登记校验值选择具体产物，旧命名兼容；歧义版本禁止任意选取。"""
    legacy = original_path(tenant_id, doc_id, revision)
    path = (
        original_path(tenant_id, doc_id, revision, expected_sha256) if expected_sha256 else legacy
    )
    if not filesystem_path(path).exists():
        path = legacy
    if (
        not filesystem_path(path).exists()
        and expected_sha256 is None
        and filesystem_path(legacy.parent).exists()
    ):
        prefix = f"{doc_id}__v{revision}__h"
        choices = [
            legacy.parent / item.name
            for item in filesystem_path(legacy.parent).iterdir()
            if item.name.startswith(prefix) and item.suffix == ".bin"
        ]
        if len(choices) > 1:
            raise EncryptionError("该版本存在多个未登记产物，读取必须提供登记校验值")
        if choices:
            path = choices[0]
    if not filesystem_path(path).exists():
        return None
    if path.resolve() != path:
        raise ValueError("原件存储路径不能经过符号链接")
    raw = filesystem_path(path).read_bytes()
    if raw.startswith(MAGIC):
        content = authenticated_content(raw, path.relative_to(storage_root()))
    elif settings.ENV != "production" or settings.ALLOW_LEGACY_PLAINTEXT_FILES:
        content = raw
    else:
        raise EncryptionError("原件需要先执行加密迁移")
    if expected_sha256 and hashlib.sha256(content).hexdigest() != expected_sha256:
        raise EncryptionError("原件与登记的 SHA256 不一致")
    return content


def archive_path(tenant_id: str, material_id: str, digest: str) -> Path:
    """党员档案影像件路径：内容寻址，同一份文件重复归档只落一份。"""
    validate_identifier(tenant_id)
    validate_identifier(material_id)
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("文件校验值无效")
    root = storage_root()
    path = root / tenant_id / "archives" / f"{material_id}__h{digest}.bin"
    if root.resolve() != root or path.parent.resolve() != path.parent or path.resolve() != path:
        raise ValueError("档案存储路径不能经过符号链接")
    return path


def save_member_archive(tenant_id: str, material_id: str, content: bytes) -> dict[str, Any]:
    """把扫描件加密后写入档案目录，返回登记用的路径与校验值。

    与制度文件原件同一套 ``seal`` + 原子写：文件离开数据库但仍然加密落盘，
    备份卷被拷走也读不出内容。
    """
    digest = hashlib.sha256(content).hexdigest()
    path = archive_path(tenant_id, material_id, digest)
    relative = path.relative_to(storage_root())
    filesystem_path(path.parent).mkdir(parents=True, exist_ok=True)
    encrypted = seal(content, file_purpose(relative))
    try:
        atomic_write(path, encrypted)
    except FileExistsError:
        if authenticated_content(filesystem_path(path).read_bytes(), relative) != content:
            raise EncryptionError("已归档影像完整性校验失败") from None
    return {"path": relative.as_posix(), "sha256": digest, "size": len(content)}


def read_member_archive(relative: str, expected_sha256: str | None = None) -> bytes | None:
    """按登记的相对路径读回档案影像件；校验值不符视为文件损坏而不是原件。"""
    if not relative:
        return None
    path = storage_root() / relative
    if path.resolve() != path or storage_root() not in path.parents:
        raise ValueError("档案存储路径不能经过符号链接或跳出存储根目录")
    if not filesystem_path(path).exists():
        return None
    raw = filesystem_path(path).read_bytes()
    if raw.startswith(MAGIC):
        content = authenticated_content(raw, path.relative_to(storage_root()))
    elif settings.ENV != "production" or settings.ALLOW_LEGACY_PLAINTEXT_FILES:
        content = raw
    else:
        raise EncryptionError("档案影像需要先执行加密迁移")
    if expected_sha256 and hashlib.sha256(content).hexdigest() != expected_sha256:
        raise EncryptionError("档案影像与登记的 SHA256 不一致")
    return content


def save_archive(tenant_id: str, resource_id: str, revision: int, snapshot: dict) -> dict:
    """把一份业务快照存成加密的归档文件（不是党员档案影像）。"""
    validate_identifier(resource_id)
    content = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str).encode()
    # 有界文件名保持 Windows 兼容，业务编号与材料都留存在加密快照中。
    identifier = "archive-" + hashlib.sha256(resource_id.encode()).hexdigest()[:32]
    return save_original(tenant_id, identifier, revision, content, "archive.json")
