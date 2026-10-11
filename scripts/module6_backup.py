"""数据库、认证加密文件和认证吊销的加密备份。恢复仅写空隔离目标，可显式续跑。"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import asyncpg  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database_privileges import UNSAFE_RUNTIME_ROLE  # noqa: E402
from app.core.encryption import EncryptionError, atomic_write, seal, unseal  # noqa: E402
from app.services.file_store import authenticated_content, file_purpose  # noqa: E402
from scripts.module6_rotate_files import validated_files  # noqa: E402

PURPOSE = "module6:backup:v1"
RESTORE_PURPOSE = "module6:restore-state:v1"
LIMIT = 512 * 1024 * 1024


def safe_root(value: str | Path) -> Path:
    root = Path(value).absolute()
    if root.resolve() != root:
        raise ValueError("目标路径不能经过符号链接")
    return root


def database_parameters(value: str, *, restore: bool = False) -> tuple[dict[str, str], str]:
    url = make_url(value)
    if url.drivername.split("+")[0] != "postgresql" or not url.database or not url.host:
        raise ValueError("必须明确PostgreSQL主机和数据库")
    mode = str(
        url.query.get("sslmode")
        or url.query.get("ssl")
        or ("verify-full" if settings.ENV == "production" else "prefer")
    )
    if settings.ENV == "production" and mode not in {"require", "verify-ca", "verify-full"}:
        raise ValueError("生产备份连接必须TLS")
    if restore and not re.fullmatch(r"module6_restore_[a-zA-Z0-9_]{1,50}", url.database):
        raise ValueError("恢复只允许新建module6_restore_前缀数据库")
    return {
        "PGHOST": url.host,
        "PGPORT": str(url.port or 5432),
        "PGUSER": url.username or "",
        "PGPASSWORD": url.password or "",
        "PGDATABASE": url.database,
        "PGSSLMODE": mode,
    }, url.database


def redis_client(url: str) -> Redis:
    if settings.ENV == "production" and make_url(url).drivername != "rediss":
        raise ValueError("生产Redis连接必须TLS")
    return Redis.from_url(url, decode_responses=False)


async def db_connect(value: str) -> asyncpg.Connection:
    env, _ = database_parameters(value)
    return await asyncpg.connect(
        host=env["PGHOST"],
        port=int(env["PGPORT"]),
        user=env["PGUSER"],
        password=env["PGPASSWORD"],
        database=env["PGDATABASE"],
        ssl=False if env["PGSSLMODE"] == "disable" else env["PGSSLMODE"],
        timeout=10,
        command_timeout=120,
    )


def registered_originals(documents: list[dict[str, Any]]) -> list[dict[str, str]]:
    """核对DB登记的全部版本；不能用目录中现存文件反推完整性。"""
    references: dict[str, str] = {}
    for document in documents:
        metadata = document.get("metadata") or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        if not isinstance(metadata, dict):
            raise ValueError("文档原件登记格式无效")
        versions = metadata.get("original_versions") or {}
        if not isinstance(versions, dict):
            raise ValueError("原件版本登记格式无效")
        entries = list(versions.values())
        if metadata.get("original_file") is not None:
            entries.append(metadata["original_file"])
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("原件版本登记无效")
            name, digest, revision = entry.get("path"), entry.get("sha256"), entry.get("revision")
            if (
                not isinstance(name, str)
                or not isinstance(digest, str)
                or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or type(revision) is not int
                or revision < 1
            ):
                raise ValueError("旧原件须先补齐相对路径、版本和SHA256登记")
            relative = PurePosixPath(name)
            if relative.as_posix() != name or relative.is_absolute() or "\\" in name:
                raise ValueError("原件登记路径无效")
            purpose = file_purpose(Path(name))
            expected = f"original:{document['tenant_id']}:{document['doc_id']}:{revision}"
            if purpose not in {expected, expected + ":" + digest}:
                raise ValueError("原件登记路径不属于当前文档和版本")
            if name in references and references[name] != digest:
                raise EncryptionError("同一原件登记了不同校验值")
            references[name] = digest
    return [{"path": name, "sha256": digest} for name, digest in sorted(references.items())]


def verify_registered_files(references: list[dict[str, str]], items: dict[str, bytes]) -> int:
    for entry in references:
        raw = items.get("files/" + entry["path"])
        if raw is None:
            raise EncryptionError("数据库登记的原件或历史版本缺失")
        content = authenticated_content(raw, Path(entry["path"]))
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise EncryptionError("原件与数据库登记的SHA256不一致")
    return len(references)


async def snapshot(value: str) -> dict[str, Any]:
    conn = await db_connect(value)
    try:
        result: dict[str, Any] = {}
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            tables = await conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
            )
            for row in tables:
                name = row["tablename"]
                if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
                    raise ValueError("非预期表名")
                digest, count = hashlib.sha256(), 0
                async for item in conn.cursor(
                    f'SELECT to_jsonb(t)::text AS value FROM "{name}" t ORDER BY value'
                ):
                    digest.update(item["value"].encode() + b"\n")
                    count += 1
                result[name] = {"count": count, "sha256": digest.hexdigest()}
            major = int(await conn.fetchval("SHOW server_version_num")) // 10000
            documents = []
            if "knowledge_docs" in result:
                documents = [
                    dict(row)
                    for row in await conn.fetch(
                        "SELECT tenant_id,doc_id,metadata FROM knowledge_docs"
                    )
                ]
            originals = registered_originals(documents)
        return {"tables": result, "server_major": major, "originals": originals}
    finally:
        await conn.close(timeout=5)


def run_pg(binary: str, args: list[str], db_url: str, payload: bytes | None = None) -> bytes:
    env, _ = database_parameters(db_url)
    if shutil.which(binary) is None:
        raise ValueError("未安装PostgreSQL备份恢复客户端")
    process = subprocess.Popen(
        [binary, *args, *(["--dbname", env["PGDATABASE"]] if payload is not None else [])],
        env={**os.environ, **env},
        stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    timer = threading.Timer(600, process.kill)
    timer.daemon = True
    timer.start()
    try:
        if payload is not None:
            out, _ = process.communicate(payload, timeout=600)
            if process.returncode:
                raise RuntimeError("pg_restore未成功")
            return out
        assert process.stdout is not None
        out = bytearray()
        while block := process.stdout.read(1024 * 1024):
            out.extend(block)
            if len(out) > LIMIT:
                raise ValueError("备份超过已声明容量")
        if process.wait(timeout=30):
            raise RuntimeError("pg_dump未成功")
        return bytes(out)
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


async def redis_snapshot(url: str) -> list[dict[str, Any]]:
    client = redis_client(url)
    rows = []
    try:
        async for key in client.scan_iter(match="auth:*", count=100):
            raw = await client.dump(key)
            ttl = await client.pttl(key)
            if raw is not None and ttl != -2:
                rows.append(
                    {
                        "key": base64.b64encode(key).decode(),
                        "dump": base64.b64encode(raw).decode(),
                        "expires_at_ms": int(time.time() * 1000) + ttl if ttl >= 0 else None,
                    }
                )
            if len(rows) > 100000:
                raise ValueError("认证备份超过10万键容量")
    finally:
        await client.aclose()
    return sorted(rows, key=lambda item: item["key"])


def packed_files(root: Path, label: str) -> list[tuple[str, bytes]]:
    root = safe_root(root)
    out, size = [], 0
    for file, _ in validated_files(root, audits=label == "audit"):
        content = file.read_bytes()
        authenticated_content(content, file.relative_to(root), audits=label == "audit")
        size += len(content)
        if size > LIMIT:
            raise ValueError("文件超过备份容量")
        out.append((label + "/" + file.relative_to(root).as_posix(), content))
    return sorted(out)


def validate_redis(raw: bytes) -> list[tuple[bytes, bytes, int | None]]:
    rows = json.loads(raw)
    if not isinstance(rows, list) or len(rows) > 100000:
        raise ValueError("认证恢复容量或格式无效")
    result, seen = [], set()
    for item in rows:
        key = base64.b64decode(item["key"], validate=True)
        payload = base64.b64decode(item["dump"], validate=True)
        expires = item["expires_at_ms"]
        if not key.startswith(b"auth:") or key in seen or not payload:
            raise ValueError("认证键越界、重复或内容为空")
        if expires is not None and (type(expires) is not int or expires < 0):
            raise ValueError("认证到期时间无效")
        seen.add(key)
        result.append((key, payload, expires))
    return result


def unpack_bundle(encrypted: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    raw = unseal(encrypted, PURPOSE)
    if len(raw) > LIMIT:
        raise ValueError("备份超过容量")
    items: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        total = 0
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if (
                str(path) != info.filename
                or path.is_absolute()
                or any(part in {"..", "."} for part in path.parts)
                or "\\" in info.filename
            ):
                raise ValueError("非法恢复路径")
            if (
                info.filename in items
                or info.is_dir()
                or (info.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise ValueError("重复路径或符号链接")
            total += info.file_size
            if total > LIMIT:
                raise ValueError("解包超过容量")
            items[info.filename] = archive.read(info)
    manifest = json.loads(items.pop("manifest.json"))
    if manifest.get("format") != 1 or set(items) != set(manifest["files"]):
        raise ValueError("未知备份格式或清单不一致")
    if not {"database.dump", "redis.json"}.issubset(items):
        raise ValueError("缺少数据库或认证吊销备份")
    for name, raw_file in items.items():
        if hashlib.sha256(raw_file).hexdigest() != manifest["files"][name]:
            raise EncryptionError("备份内容校验失败")
        if name in {"database.dump", "redis.json"}:
            continue
        prefix, relative = name.split("/", 1)
        if prefix not in {"files", "audit"}:
            raise ValueError("非预期恢复目录")
        authenticated_content(raw_file, Path(relative), audits=prefix == "audit")
    verify_registered_files(manifest["database"]["originals"], items)
    validate_redis(items["redis.json"])
    return manifest, items


async def backup(output: Path, source: str, redis_url: str, quiesced: bool) -> dict[str, Any]:
    if not quiesced:
        raise ValueError("必须暂停业务写入和任务，并显式指定--quiesced")
    output = safe_root(output)
    before = await snapshot(source)
    dump = await asyncio.to_thread(
        run_pg,
        os.getenv("PG_DUMP_BIN", "pg_dump"),
        ["--format=custom", "--no-owner", "--no-privileges"],
        source,
    )
    entries = [("database.dump", dump)]
    entries += packed_files(Path(settings.FILE_STORAGE_DIR), "files")
    entries += packed_files(Path(settings.AUDIT_SPOOL_DIR), "audit")
    verify_registered_files(before["originals"], dict(entries))
    entries.append(
        ("redis.json", json.dumps(await redis_snapshot(redis_url), sort_keys=True).encode())
    )
    if before != await snapshot(source):
        raise ValueError("数据库在备份过程中改变，备份未发布")
    manifest = {
        "format": 1,
        "created_at": time.time(),
        "database": before,
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in entries},
    }
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, raw in entries:
            archive.writestr(name, raw)
        archive.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
    if memory.tell() > LIMIT:
        raise ValueError("总备份容量超过512MiB")
    atomic_write(output, seal(memory.getvalue(), PURPOSE))
    return {
        "status": "backed_up",
        "bytes": output.stat().st_size,
        "tables": len(before["tables"]),
        "registered_originals_verified": len(before["originals"]),
        "data_checksum": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
    }


async def role_preflight(conn: asyncpg.Connection, role: str) -> None:
    from scripts.module6_runtime_role import validate_role

    validate_role(role)
    unsafe = await conn.fetchval("SELECT " + UNSAFE_RUNTIME_ROLE.replace(":role", "$1"), role)
    if unsafe:
        raise ValueError("运行账号未建立或拥有/继承所有者、超级用户权限")


async def restore(
    bundle: Path,
    target: str,
    redis_url: str,
    files: Path,
    audit: Path,
    runtime_role: str | None,
    apply: bool,
    resume: bool = False,
) -> dict[str, Any]:
    parameters, _ = database_parameters(target, restore=True)
    encrypted = bundle.read_bytes()
    manifest, items = unpack_bundle(encrypted)  # 全部内层 AEAD/路径在任何写入前校验。
    files, audit = safe_root(files), safe_root(audit)
    if files == audit or files in audit.parents or audit in files.parents:
        raise ValueError("文件与审计恢复目录必须独立")
    identity = {
        "bundle_sha256": hashlib.sha256(encrypted).hexdigest(),
        "database": hashlib.sha256(
            json.dumps(
                {key: value for key, value in parameters.items() if key != "PGPASSWORD"},
                sort_keys=True,
            ).encode()
        ).hexdigest(),
        "redis": hashlib.sha256(redis_url.encode()).hexdigest(),
        "files": str(files),
        "audit": str(audit),
    }
    marker = files / ".module6-restore-state"
    continuing = False
    if marker.exists():
        if not resume or json.loads(unseal(marker.read_bytes(), RESTORE_PURPOSE)) != identity:
            raise ValueError("续跑必须显式--resume，且目标与备份必须和加密检查点一致")
        continuing = True
    elif resume:
        raise ValueError("没有本工具建立的加密检查点，禁止接管已有目标")
    expected, existing = manifest["database"], await snapshot(target)
    if existing["server_major"] != expected["server_major"]:
        raise ValueError("恢复演练要求相同PostgreSQL主版本")
    if existing["tables"] and (not continuing or existing != expected):
        raise ValueError("目标已有不同数据库内容，禁止覆盖或清理")
    allowed = {"files": files, "audit": audit}
    for prefix, root in allowed.items():
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_symlink() or path.resolve() != path.absolute():
                raise ValueError("目标不能包含符号链接")
            if not path.is_file() or path == marker:
                continue
            name = prefix + "/" + path.relative_to(root).as_posix()
            if (
                not continuing
                or name not in items
                or hashlib.sha256(path.read_bytes()).hexdigest() != manifest["files"][name]
            ):
                raise ValueError("目标已有不同材料，禁止覆盖或清理")
    conn = await db_connect(target)
    try:
        if runtime_role:
            await role_preflight(conn, runtime_role)
    finally:
        await conn.close(timeout=5)
    if not existing["tables"] and shutil.which(os.getenv("PG_RESTORE_BIN", "pg_restore")) is None:
        raise ValueError("未安装PostgreSQL恢复客户端")
    client = redis_client(redis_url)
    redis_rows = validate_redis(items["redis.json"])
    expected_redis = {key: raw for key, raw, _ in redis_rows}
    try:
        if not continuing and await client.dbsize():
            raise ValueError("Redis恢复目标必须为空")
        if continuing:
            async for key in client.scan_iter():
                if key not in expected_redis or await client.dump(key) != expected_redis[key]:
                    raise ValueError("Redis目标已有不同认证内容，禁止覆盖")
        if not apply:
            return {
                "status": "validated",
                "applied": False,
                "resuming": continuing,
                "table_count": len(expected["tables"]),
            }
        if not continuing:
            atomic_write(
                marker, seal(json.dumps(identity, sort_keys=True).encode(), RESTORE_PURPOSE)
            )
        if not existing["tables"]:
            await asyncio.to_thread(
                run_pg,
                os.getenv("PG_RESTORE_BIN", "pg_restore"),
                ["--exit-on-error", "--single-transaction", "--no-owner", "--no-privileges"],
                target,
                items["database.dump"],
            )
        if await snapshot(target) != expected:
            raise EncryptionError("恢复后数据库计数或数据哈希不一致")
        restored = 0
        for name, raw in items.items():
            if not name.startswith(("files/", "audit/")):
                continue
            prefix, relative = name.split("/", 1)
            destination = allowed[prefix] / relative
            if destination.resolve() != destination.absolute():
                raise ValueError("恢复路径经过符号链接")
            try:
                atomic_write(destination, raw)
            except FileExistsError:
                if not continuing or destination.read_bytes() != raw:
                    raise EncryptionError("文件恢复出现冲突") from None
            authenticated_content(
                destination.read_bytes(), Path(relative), audits=prefix == "audit"
            )
            restored += 1
        for key, raw, expires in redis_rows:
            now = int(time.time() * 1000)
            if expires is not None and expires <= now:
                continue
            if not await client.exists(key):
                await client.restore(key, max(1, expires - now) if expires is not None else 0, raw)
            if await client.dump(key) != raw:
                raise EncryptionError("认证吊销恢复校验失败")
        permissions = "pending_configuration"
        if runtime_role:
            from scripts.module6_runtime_role import statements

            conn = await db_connect(target)
            try:
                await role_preflight(conn, runtime_role)
                async with conn.transaction():
                    for statement in statements(runtime_role):
                        await conn.execute(statement)
                    ok = await conn.fetchval(
                        "SELECT has_table_privilege($1,'audit_logs','SELECT') "
                        "AND has_table_privilege($1,'audit_logs','INSERT') "
                        "AND NOT has_table_privilege($1,'audit_logs','UPDATE,DELETE,TRUNCATE') "
                        "AND NOT has_any_column_privilege($1,'audit_logs','UPDATE')",
                        runtime_role,
                    )
                    if not ok:
                        raise ValueError("审计权限仍允许修改")
                permissions = "verified"
            finally:
                await conn.close(timeout=5)
        return {
            "status": "restored" if runtime_role else "restored_pending_permissions",
            "data_verified": True,
            "files_verified": restored,
            "registered_originals_verified": len(expected["originals"]),
            "permissions": permissions,
        }
    finally:
        await client.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--output", type=Path, required=True)
    b.add_argument("--quiesced", action="store_true")
    r = sub.add_parser("restore")
    r.add_argument("--input", type=Path, required=True)
    r.add_argument("--files", type=Path, required=True)
    r.add_argument("--audit", type=Path, required=True)
    r.add_argument("--runtime-role")
    r.add_argument("--apply", action="store_true")
    r.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "backup":
            result = asyncio.run(
                backup(
                    args.output, os.environ["DATABASE_URL"], os.environ["REDIS_URL"], args.quiesced
                )
            )
        else:
            result = asyncio.run(
                restore(
                    args.input,
                    os.environ["RESTORE_DATABASE_URL"],
                    os.environ["RESTORE_REDIS_URL"],
                    args.files,
                    args.audit,
                    args.runtime_role,
                    args.apply,
                    args.resume,
                )
            )
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] != "restored_pending_permissions" else 2
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
