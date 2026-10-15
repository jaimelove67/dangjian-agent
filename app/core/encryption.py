"""AES-256-GCM 信封。密钥只来自运行环境，AAD 绑定文件用途与对象。"""

import base64
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

MAGIC = b"DJAE1\n"


def filesystem_path(path: Path) -> Path:
    """返回用于实际系统调用的路径；Windows 上超过 MAX_PATH(260) 时加 ``\\\\?\\`` 前缀。

    仅用于读写/建删等系统调用，逻辑判断（relative_to、路径包含）仍用原 Path，
    这样长路径（长存储根 + 内容寻址文件名）不会在发布阶段静默失败。
    """
    if os.name != "nt":
        return path
    text = str(path)
    if text.startswith("\\\\?\\") or not path.is_absolute():
        return path
    if text.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + text[2:])
    return Path("\\\\?\\" + text)


class EncryptionError(ValueError):
    pass


def keyring() -> tuple[str, dict[str, bytes]]:
    raw = os.getenv("FILE_ENCRYPTION_KEYS")
    values = json.loads(raw) if raw else settings.FILE_ENCRYPTION_KEYS
    active = os.getenv("FILE_ENCRYPTION_ACTIVE_KEY") or settings.FILE_ENCRYPTION_ACTIVE_KEY
    if not values and settings.ENV != "production":
        # 仅开发兼容；生产就绪检查拒绝此路径。
        return "development", {
            "development": hashlib.sha256(
                ("file-development:" + settings.SECRET_KEY).encode()
            ).digest()
        }
    try:
        keys = {str(name): base64.b64decode(value, validate=True) for name, value in values.items()}
    except (ValueError, TypeError, AttributeError) as exc:
        raise EncryptionError("文件加密密钥格式无效") from exc
    if active not in keys or any(len(value) != 32 for value in keys.values()):
        raise EncryptionError("必须配置有效的 AES-256 当前密钥和密钥环")
    return active, keys


def seal(content: bytes, purpose: str, *, key_id: str | None = None) -> bytes:
    active, keys = keyring()
    selected = key_id or active
    if selected not in keys:
        raise EncryptionError("加密密钥版本不存在")
    nonce = os.urandom(12)
    ciphertext = AESGCM(keys[selected]).encrypt(nonce, content, purpose.encode())
    envelope = {
        "key_id": selected,
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }
    return MAGIC + json.dumps(envelope, separators=(",", ":")).encode()


def unseal(content: bytes, purpose: str) -> bytes:
    if not content.startswith(MAGIC):
        raise EncryptionError("文件不是受支持的加密信封")
    _, keys = keyring()
    try:
        envelope: dict[str, Any] = json.loads(content[len(MAGIC) :])
        key = keys[envelope["key_id"]]
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        return AESGCM(key).decrypt(nonce, ciphertext, purpose.encode())
    except (KeyError, ValueError, TypeError, InvalidTag) as exc:
        raise EncryptionError("文件完整性验证失败或密钥不可用") from exc


def atomic_write(path: Path, value: bytes, *, replace: bool = False) -> None:
    """完整写入并fsync后原子发布，只生成加密的同目录临时文件。"""
    filesystem_path(path.parent).mkdir(parents=True, exist_ok=True)
    # 临时名保持定长且极短：目标名本身已接近 Windows MAX_PATH，再拼 38 个字符会直接失败。
    temporary = path.with_name("." + uuid.uuid4().hex[:12] + ".part")
    raw_temporary = filesystem_path(temporary)
    try:
        with raw_temporary.open("xb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(raw_temporary, filesystem_path(path))
        else:
            os.link(raw_temporary, filesystem_path(path))
    finally:
        if raw_temporary.exists():
            raw_temporary.unlink()
