"""发布演示用中央制度节选（一次性运维脚本）。

背景：``seed_knowledge_docs.py`` 默认把演示资料标为学校范围 / expired，避免把
未核验节选当成正式制度。但这样会让入党申请人等学校角色检索不到任何中央文件，
问答因此全部拒答。本脚本只把 3 篇中央节选改为公共可见、现行有效，并保留标题
中的「[未核验演示]」前缀；正文和向量都不改。

用法（在应用容器或能连到目标库的环境运行）：

    python scripts/publish_demo_central_docs.py --tenant-id <租户ID> --yes

这是演示数据修复，不替代知识库的审核发布流程；正式制度仍应通过入库与审核接口
发布。脚本幂等：重复运行只重复写入同样的元数据。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.append(str(Path(__file__).parent.parent))

from app.core.config import settings  # noqa: E402 - 直接运行脚本时先加入项目根目录
from app.models.knowledge import EmbeddingChunk, KnowledgeDoc  # noqa: E402

DOC_AUTHORITY = {
    "DEMO-DOC-PARTY-CONSTITUTION": "party_constitution",
    "DEMO-DOC-BRANCH-REGULATION": "party_regulation",
    "DEMO-DOC-MEMBER-EDU-REGULATION": "party_regulation",
}
DOC_IDS = tuple(DOC_AUTHORITY)


async def publish_demo_central_docs(tenant_id: str) -> list[tuple[str, int, int]]:
    """把 3 篇中央节选改为公共可见、现行有效，返回 (doc_id, 片段数, 向量数)。"""
    engine = create_async_engine(settings.DATABASE_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as db:
            documents = (
                (
                    await db.execute(
                        select(KnowledgeDoc).where(
                            KnowledgeDoc.tenant_id == tenant_id,
                            KnowledgeDoc.doc_id.in_(DOC_IDS),
                            KnowledgeDoc.is_deleted.is_(False),
                        )
                    )
                )
                .scalars()
                .all()
            )
            found = {document.doc_id for document in documents}
            missing = sorted(set(DOC_IDS) - found)
            if missing:
                raise SystemExit(f"租户 {tenant_id} 缺少文档：{', '.join(missing)}")

            for document in documents:
                document.level = "central"
                document.visibility = "public"
                document.security_level = "public"
                document.review_status = "published"
                document.status = "effective"
                document.validity = "effective"
                document.expiration_date = None
                document.authority = DOC_AUTHORITY[document.doc_id]
            await db.commit()

            result: list[tuple[str, int, int]] = []
            for document in documents:
                chunks = (
                    await db.execute(
                        select(func.count())
                        .select_from(EmbeddingChunk)
                        .where(
                            EmbeddingChunk.doc_id == document.id,
                            EmbeddingChunk.tenant_id == tenant_id,
                            EmbeddingChunk.is_deleted.is_(False),
                        )
                    )
                ).scalar_one()
                vectors = (
                    await db.execute(
                        select(func.count())
                        .select_from(EmbeddingChunk)
                        .where(
                            EmbeddingChunk.doc_id == document.id,
                            EmbeddingChunk.tenant_id == tenant_id,
                            EmbeddingChunk.is_deleted.is_(False),
                            EmbeddingChunk.embedding.isnot(None),
                        )
                    )
                ).scalar_one()
                result.append((document.doc_id, int(chunks), int(vectors)))
            return result
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="发布演示用中央制度节选")
    parser.add_argument("--tenant-id", required=True, help="学校租户 ID")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="确认执行演示数据修复；未提供时只做检查不写库",
    )
    args = parser.parse_args()

    if not args.yes:
        print("未提供 --yes：仅检查文档是否存在，不修改数据。")
        engine = create_async_engine(settings.DATABASE_URL)

        async def check() -> None:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                rows = (
                    await db.execute(
                        select(KnowledgeDoc.doc_id, KnowledgeDoc.status)
                        .where(
                            KnowledgeDoc.tenant_id == args.tenant_id,
                            KnowledgeDoc.doc_id.in_(DOC_IDS),
                            KnowledgeDoc.is_deleted.is_(False),
                        )
                    )
                ).all()
                for doc_id, status in rows:
                    print(f"  {doc_id}: {status}")
            await engine.dispose()

        asyncio.run(check())
        return

    rows = asyncio.run(publish_demo_central_docs(args.tenant_id))
    for doc_id, chunks, vectors in rows:
        print(f"[ok] {doc_id}: 片段 {chunks}，向量 {vectors}")
        if not vectors:
            print("     [warn] 该文档没有向量，问答不会引用；请先运行向量化接口")
    print("完成。请用申请人、学校管理员、院系管理员、支部书记、组织员、党员账号分别验证检索。")


if __name__ == "__main__":
    main()
