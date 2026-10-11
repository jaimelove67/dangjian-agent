"""仅在Linux临时CI库实际构建镜像、演练迁移回退、TLS代理与加密恢复。不会使用正式库。"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.encryption import MAGIC  # noqa: E402
from app.services.file_store import save_original  # noqa: E402
from scripts import module6_backup as archive  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], log: Path, *, environment: dict | None = None) -> None:
    with log.open("a", encoding="utf-8") as stream:
        subprocess.run(
            args,
            cwd=ROOT,
            env=environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=1800,
        )


async def migrate(url, revision: str, downgrade: bool = False) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:

            def apply(sync):
                config = Config(str(ROOT / "alembic.ini"))
                config.attributes["connection"] = sync
                (command.downgrade if downgrade else command.upgrade)(config, revision)

            await conn.run_sync(apply)
    finally:
        await engine.dispose()


def get(url: str, context=None) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5, context=context) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


async def check(output: Path, isolated: bool) -> dict:
    url = make_url(settings.DATABASE_URL)
    if (
        not isolated
        or settings.ENV != "testing"
        or url.database != "module6_native_ci"
        or url.host not in {"127.0.0.1", "localhost"}
    ):
        raise ValueError("必须显式--isolated且使用本机module6_native_ci临时基础库")
    if platform.system() != "Linux" or os.getuid() == 0 or shutil.which("docker") is None:
        return {"status": "unexecuted", "reason": "linux_nonroot_docker_environment_required"}
    output.parent.mkdir(parents=True, exist_ok=True)
    log = output.parent / "container.log"
    suffix = uuid.uuid4().hex[:12]
    names = ["module6_source_" + suffix, "module6_restore_" + suffix]
    role = "module6_rt_" + suffix
    containers = ["module6_app_" + suffix, "module6_proxy_" + suffix]
    images = ["party-module6-ci:" + suffix, "party-module6-front-ci:" + suffix]
    admin = create_async_engine(
        url.set(database="postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    created = []
    os.environ["FILE_ENCRYPTION_KEYS"] = json.dumps(
        {"ci": base64.b64encode(os.urandom(32)).decode()}
    )
    os.environ["FILE_ENCRYPTION_ACTIVE_KEY"] = "ci"
    source = url.set(database=names[0]).render_as_string(hide_password=False)
    target = url.set(database=names[1]).render_as_string(hide_password=False)
    temp_root = ROOT / "tmp"
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="module6-native-", dir=temp_root) as directory:
        owned = Path(directory).resolve()
        if not owned.is_relative_to(temp_root.resolve()):
            raise ValueError("临时目标不在预定验收目录")
        files, audit = owned / "files", owned / "audit"
        files.mkdir(mode=0o700)
        audit.mkdir(mode=0o700)
        settings.FILE_STORAGE_DIR, settings.AUDIT_SPOOL_DIR = str(files), str(audit)
        os.environ["FILE_STORAGE_DIR"] = str(files)
        source_redis = (
            make_url(settings.REDIS_URL).set(database="14").render_as_string(hide_password=False)
        )
        target_redis = (
            make_url(settings.REDIS_URL).set(database="15").render_as_string(hide_password=False)
        )
        fixture_id = str(uuid.uuid4())
        fixture = b"NOT_REAL_SCHOOL_MATERIAL_CI"
        try:
            for name in names:
                assert re.fullmatch(r"module6_(source|restore)_[a-f0-9]{12}", name)
                async with admin.connect() as conn:
                    await conn.execute(text(f'CREATE DATABASE "{name}"'))
                created.append(name)
            await migrate(source, "head")
            conn = await archive.db_connect(source)
            try:
                await conn.execute(
                    "INSERT INTO tenants(id,tenant_id,name,tenant_type,path,config,is_active,"
                    "config_version,created_at,updated_at,is_deleted) "
                    "VALUES($1,$1,'独立CI资料','school',$2,'{}',true,0,now(),now(),false)",
                    fixture_id,
                    "/" + fixture_id,
                )
            finally:
                await conn.close()
            saved = save_original(fixture_id, fixture_id, 1, fixture, "ci.txt")
            assert fixture not in (files / saved["path"]).read_bytes()
            conn = await archive.db_connect(source)
            try:
                await conn.execute(
                    "INSERT INTO knowledge_docs(id,tenant_id,doc_id,file_name,title,issuer,level,"
                    "visibility,security_level,effective_date,status,tags,metadata,created_at,"
                    "updated_at,is_deleted) VALUES($1,$1,$1,'ci.txt','独立CI原件','CI','school',"
                    "'school','internal',CURRENT_DATE,'effective','{}',$2::json,now(),now(),false)",
                    fixture_id,
                    json.dumps(
                        {
                            "content_revision": 1,
                            "original_file": saved,
                            "original_versions": {"1": saved},
                        }
                    ),
                )
            finally:
                await conn.close()
            missing = files / saved["path"]
            hidden = owned / "deliberately-missing-original.bin"
            missing.rename(hidden)
            try:
                await archive.backup(owned / "must-not-publish.bin", source, source_redis, True)
                raise AssertionError("丢失已登记原件没有使备份失败")
            except archive.EncryptionError:
                assert not (owned / "must-not-publish.bin").exists()
            finally:
                hidden.rename(missing)
            run(["docker", "build", "-t", images[0], "-f", "Dockerfile", "."], log)
            run(["docker", "build", "-t", images[1], "-f", "Dockerfile.frontend", "."], log)
            child = {
                **os.environ,
                "ENV": "testing",
                "DATABASE_URL": source,
                "REDIS_URL": source_redis,
                "JOB_WORKER_ENABLED": "false",
                "FILE_STORAGE_DIR": "/materials",
                "AUDIT_SPOOL_DIR": "/audit",
                "DASHSCOPE_API_KEY": "",
            }
            run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    containers[0],
                    "--network",
                    "host",
                    "--user",
                    f"{os.getuid()}:{os.getgid()}",
                    "--read-only",
                    "--tmpfs",
                    "/tmp",
                    "--mount",
                    f"type=bind,src={files},dst=/materials",
                    "--mount",
                    f"type=bind,src={audit},dst=/audit",
                    *[
                        arg
                        for key in (
                            "ENV",
                            "DATABASE_URL",
                            "REDIS_URL",
                            "JOB_WORKER_ENABLED",
                            "FILE_STORAGE_DIR",
                            "AUDIT_SPOOL_DIR",
                            "FILE_ENCRYPTION_KEYS",
                            "FILE_ENCRYPTION_ACTIVE_KEY",
                            "DASHSCOPE_API_KEY",
                        )
                        for arg in ("--env", key)
                    ],
                    images[0],
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ],
                log,
                environment=child,
            )
            live = False
            for _ in range(60):
                try:
                    live = get("http://127.0.0.1:8000/api/v1/health/live")[0] == 200
                except OSError:
                    pass
                if live:
                    break
                await asyncio.sleep(0.5)
            if not live:
                raise RuntimeError("实际运行镜像未通过存活检查")
            code, body = get("http://127.0.0.1:8000/api/v1/health/ready")
            readiness = json.loads(body)
            assert code == 503 and readiness["checks"]["schema"] == "healthy"
            assert readiness["checks"]["models"] == "configuration_required"
            certs = owned / "tls"
            certs.mkdir(mode=0o700)
            run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-keyout",
                    str(certs / "privkey.pem"),
                    "-out",
                    str(certs / "fullchain.pem"),
                    "-days",
                    "1",
                    "-subj",
                    "/CN=localhost",
                    "-addext",
                    "subjectAltName=DNS:localhost,IP:127.0.0.1",
                ],
                log,
            )
            run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    containers[1],
                    "--network",
                    "host",
                    "--add-host",
                    "app:127.0.0.1",
                    "--user",
                    f"{os.getuid()}:{os.getgid()}",
                    "--read-only",
                    "--tmpfs",
                    f"/var/run:uid={os.getuid()},gid={os.getgid()}",
                    "--tmpfs",
                    f"/var/cache/nginx:uid={os.getuid()},gid={os.getgid()}",
                    "--mount",
                    f"type=bind,src={certs},dst=/run/tls,readonly",
                    images[1],
                ],
                log,
            )
            context = ssl.create_default_context(cafile=str(certs / "fullchain.pem"))
            https = False
            for _ in range(40):
                try:
                    https = get("https://127.0.0.1:8443/api/v1/health/live", context)[0] == 200
                except OSError:
                    pass
                if https:
                    break
                await asyncio.sleep(0.5)
            assert https and get("https://127.0.0.1:8443/", context)[0] == 200
            assert get("https://127.0.0.1:8443/api/health/live", context)[0] == 200
            # 停止此次创建的容器，演练写入暂停后的程序/数据库回退与再升级。
            for container in containers:
                run(["docker", "rm", "-f", container], log)
            before = await archive.snapshot(source)
            await migrate(source, "009_member_workflow", downgrade=True)
            await migrate(source, "head")
            assert await archive.snapshot(source) == before
            client = archive.redis_client(source_redis)
            try:
                await client.set(b"auth:revoked:native-ci", b"1", ex=3600)
            finally:
                await client.aclose()
            bundle = owned / "backup.bin"
            backed = await archive.backup(bundle, source, source_redis, True)
            assert bundle.read_bytes().startswith(MAGIC)
            assert fixture not in bundle.read_bytes()
            async with admin.connect() as conn:
                await conn.execute(
                    text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE')
                )
            destination, spool = owned / "restored-files", owned / "restored-audit"
            actual_write = archive.atomic_write
            failed_once = False

            def interrupted(path, content, **kwargs):
                nonlocal failed_once
                if Path(path).suffix == ".bin" and not failed_once:
                    failed_once = True
                    raise OSError("synthetic_interruption_after_database_restore")
                actual_write(path, content, **kwargs)

            archive.atomic_write = interrupted
            try:
                await archive.restore(bundle, target, target_redis, destination, spool, role, True)
                raise AssertionError("中断反例未触发")
            except OSError:
                pass
            finally:
                archive.atomic_write = actual_write
            restored = await archive.restore(
                bundle, target, target_redis, destination, spool, role, True, resume=True
            )
            assert restored["status"] == "restored" and restored["permissions"] == "verified"
            assert await archive.snapshot(target) == await archive.snapshot(source)
            assert (
                hashlib.sha256((destination / saved["path"]).read_bytes()).hexdigest()
                == hashlib.sha256((files / saved["path"]).read_bytes()).hexdigest()
            )
            conn = await archive.db_connect(target)
            try:
                privileges = await conn.fetchval(
                    "SELECT has_table_privilege($1,'audit_logs','SELECT,INSERT') "
                    "AND NOT has_table_privilege($1,'audit_logs','UPDATE,DELETE,TRUNCATE') "
                    "AND NOT has_any_column_privilege($1,'audit_logs','UPDATE')",
                    role,
                )
                assert privileges
                for query in (
                    "UPDATE audit_logs SET result='success'",
                    "DELETE FROM audit_logs",
                    "TRUNCATE audit_logs",
                ):
                    async with conn.transaction():
                        await conn.execute(f'SET LOCAL ROLE "{role}"')
                        try:
                            async with conn.transaction():
                                await conn.execute(query)
                        except Exception as exc:
                            if type(exc).__name__ != "InsufficientPrivilegeError":
                                raise
                        else:
                            raise AssertionError("运行账号能修改审计")
            finally:
                await conn.close()
            return {
                "status": "passed",
                "official_school": "pending_configuration",
                "backend_image_built": True,
                "frontend_image_built": True,
                "liveness_verified": True,
                "pending_readiness_503_verified": True,
                "tls_proxy_verified": True,
                "migration_rollback_data_verified": True,
                "missing_registered_original_rejected": True,
                "encrypted_backup": backed,
                "restore": restored,
                "interrupted_restore_resumed": True,
                "audit_runtime_mutations_denied": True,
                "notice": "隔离CI证据，不代表校方审批、真实模型连通或完整问答P95验收。",
            }
        finally:
            for container in containers:
                (
                    run(["docker", "rm", "-f", container], log)
                    if subprocess.run(
                        ["docker", "inspect", container],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    ).returncode
                    == 0
                    else None
                )
            for name in reversed(created):
                assert re.fullmatch(r"module6_(source|restore)_[a-f0-9]{12}", name)
                async with admin.connect() as conn:
                    await conn.execute(text(f'DROP DATABASE "{name}"'))
            async with admin.connect() as conn:
                await conn.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
            await admin.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {"status": "failed"}
    try:
        result = asyncio.run(check(args.output, args.isolated))
    except Exception as exc:
        result = {"status": "failed", "error": type(exc).__name__}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 2 if result["status"] == "unexecuted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
