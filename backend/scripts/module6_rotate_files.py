"""已保留所有旧密钥后验证/迁移/轮换文件。默认只验证；不删除旧密钥或业务文件。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings  # noqa: E402
from app.core.encryption import (  # noqa: E402
    MAGIC,
    EncryptionError,
    atomic_write,
    keyring,
    seal,
    unseal,
)
from app.services.file_store import authenticated_content, file_purpose, storage_root  # noqa: E402


def validated_files(root: Path, *, audits: bool = False) -> list[tuple[Path, str]]:
    root = root.absolute()
    if root.resolve() != root:
        raise ValueError("根目录不能经过符号链接")
    result: list[tuple[Path, str]] = []
    if not root.exists():
        return result
    for path in root.rglob("*"):
        if path.is_symlink() or path.resolve() != path.absolute():
            raise ValueError("不能轮换符号链接")
        if not path.is_file():
            continue
        if (audits and path.suffix == ".audit") or (not audits and path.suffix == ".bin"):
            purpose = file_purpose(path.relative_to(root), audits=audits)
        else:
            continue
        result.append((path, purpose))
    return result


def rotate(
    root: Path, *, apply: bool = False, allow_plaintext: bool = False, audits: bool = False
) -> dict[str, int | str | bool]:
    active, _ = keyring()
    files = validated_files(root, audits=audits)
    original_digests: dict[Path, str] = {}
    # 先验证全部文件，遇到损坏或缺少旧密钥时不开始替换。
    for path, purpose in files:
        raw = path.read_bytes()
        if raw.startswith(MAGIC):
            authenticated_content(raw, path.relative_to(root), audits=audits)
        elif not allow_plaintext or audits:
            raise EncryptionError("明文迁移需要显式允许，审计缓冲必须已加密")
        original_digests[path] = hashlib.sha256(raw).hexdigest()
    migrated = 0
    if apply:
        for path, purpose in files:
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != original_digests[path]:
                raise EncryptionError("验证后文件已改变，停止轮换")
            content = (
                authenticated_content(raw, path.relative_to(root), audits=audits)
                if raw.startswith(MAGIC)
                else raw
            )
            encrypted = seal(content, purpose)
            if unseal(encrypted, purpose) != content:
                raise EncryptionError("新密钥验证失败")
            atomic_write(path, encrypted, replace=True)
            migrated += 1
    return {
        "status": "rotated" if apply else "validated",
        "files": len(files),
        "migrated": migrated,
        "active_key_id": active,
        "applied": apply,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--allow-legacy-plaintext", action="store_true")
    p.add_argument("--audit-spool", action="store_true")
    args = p.parse_args()
    try:
        root = Path(settings.AUDIT_SPOOL_DIR) if args.audit_spool else storage_root()
        print(
            json.dumps(
                rotate(
                    root,
                    apply=args.apply,
                    allow_plaintext=args.allow_legacy_plaintext,
                    audits=args.audit_spool,
                ),
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
