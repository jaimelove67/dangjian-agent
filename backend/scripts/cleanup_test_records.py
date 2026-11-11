"""按编号软删除本轮测试留下的会议、个人材料或发展材料。

只做 ``is_deleted=true``，不物理删除、不删版本、审计、回执或文件卷；每一步写入
AuditLog，便于维护者核对。默认 dry-run，必须显式 ``--confirm`` 才写库。

用法（仓库根目录，使用已安装后端依赖的 Python）：

    # 先看会处理哪些记录（不写库）
    python backend/scripts/cleanup_test_records.py \\
        --actor admin --reason "清理2026-11体验测试数据" \\
        --meeting-id <id> --personal-material-id <id> --development-material-id <id>

    # 确认后执行
    python backend/scripts/cleanup_test_records.py ... --confirm

注意：只在 development/testing 环境运行；执行前自行备份数据库。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import pkgutil
import sys
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

sys.path.append(str(Path(__file__).parent.parent))

import app.models as _models  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.tenant import bypass_tenant_filter  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.models.audit import AuditLog  # noqa: E402
from app.models.meeting import MeetingRecord  # noqa: E402
from app.models.member import MemberMaterial  # noqa: E402
from app.models.user import User  # noqa: E402

for _, _name, _ in pkgutil.iter_modules(_models.__path__):
    importlib.import_module(f"app.models.{_name}")


def _print_record(label: str, record: object) -> None:
    if isinstance(record, MeetingRecord):
        print(
            f"[{label}] 会议：{record.title} | 状态={record.review_status} | "
            f"归档={'是' if record.archived_at else '否'} | tenant={record.tenant_id}"
        )
    elif isinstance(record, MemberMaterial):
        kind = "个人材料" if record.user_id or record.submission_key else "发展材料"
        print(
            f"[{label}] {kind}：{record.title or record.material_type} | "
            f"核验={record.review_status} | tenant={record.tenant_id}"
        )


async def _find_actor(db: AsyncSession, username: str) -> User:
    actor = (
        await db.execute(select(User).where(User.username == username, User.is_deleted.is_(False)))
    ).scalar_one_or_none()
    if actor is None:
        raise SystemExit(f"[x] 未找到操作人账号：{username}")
    return actor


async def _load(db: AsyncSession, model, record_id: str, tenant_id: str):
    return (
        await db.execute(
            select(model).where(
                model.id == record_id,
                model.tenant_id == tenant_id,
                model.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()


async def _soft_delete(db: AsyncSession, record, actor: User, reason: str, kind: str) -> None:
    record.is_deleted = True
    db.add(
        AuditLog(
            tenant_id=record.tenant_id,
            user_id=str(actor.id),
            user_name=actor.name,
            action="cleanup_test_data",
            resource_type=kind,
            resource_id=str(record.id),
            data_level="sensitive",
            request_id=f"cleanup-{uuid.uuid4()}",
            result="success",
            old_value={"is_deleted": False},
            new_value={"is_deleted": True, "reason": reason},
        )
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="按编号软删除测试业务记录")
    parser.add_argument("--actor", required=True, help="执行清理的管理员登录账号")
    parser.add_argument("--reason", required=True, help="清理原因，写入审计")
    parser.add_argument("--meeting-id", help="会议记录编号")
    parser.add_argument("--personal-material-id", help="个人材料编号")
    parser.add_argument("--development-material-id", help="发展材料编号")
    parser.add_argument("--confirm", action="store_true", help="真正写库；默认只预演")
    args = parser.parse_args()

    if settings.ENV not in {"development", "testing"}:
        raise SystemExit("[x] 只允许在 development/testing 环境运行")
    if not any((args.meeting_id, args.personal_material_id, args.development_material_id)):
        raise SystemExit("[x] 至少提供一个记录编号")
    if len(args.reason.strip()) < 4:
        raise SystemExit("[x] 请填写至少 4 个字的清理原因")

    session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with bypass_tenant_filter():
        async with session_factory() as db:
            actor = await _find_actor(db, args.actor)
            tenant_id = str(actor.tenant_id)
            print(f"操作人：{actor.name} ({actor.username})；租户：{tenant_id}")
            print(f"模式：{'执行软删除' if args.confirm else '预演（不写库）'}")

            targets: list[tuple[object, str]] = []
            if args.meeting_id:
                record = await _load(db, MeetingRecord, args.meeting_id, tenant_id)
                if record is None:
                    raise SystemExit(f"[x] 会议不存在或已删除：{args.meeting_id}")
                _print_record("会议", record)
                targets.append((record, "meeting"))
            if args.personal_material_id:
                record = await _load(db, MemberMaterial, args.personal_material_id, tenant_id)
                if record is None:
                    raise SystemExit(f"[x] 个人材料不存在或已删除：{args.personal_material_id}")
                if not (record.user_id or record.submission_key):
                    raise SystemExit("[x] 该编号不是个人提交材料，请改用 --development-material-id")
                _print_record("个人材料", record)
                targets.append((record, "member_material"))
            if args.development_material_id:
                record = await _load(db, MemberMaterial, args.development_material_id, tenant_id)
                if record is None:
                    raise SystemExit(f"[x] 发展材料不存在或已删除：{args.development_material_id}")
                if record.user_id or record.submission_key:
                    raise SystemExit("[x] 该编号是个人材料，请改用 --personal-material-id")
                _print_record("发展材料", record)
                targets.append((record, "member_material"))

            if not args.confirm:
                print("\n预演完成；确认后加 --confirm 执行软删除。")
                return 0

            for record, kind in targets:
                await _soft_delete(db, record, actor, args.reason.strip(), kind)
            await db.commit()
            print(f"\n已软删除 {len(targets)} 条记录，并写入审计。")
            return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
