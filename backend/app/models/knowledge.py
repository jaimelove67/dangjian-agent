"""知识文档表模型"""

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Computed, Date, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KnowledgeDoc(Base):
    """知识文档表

    存储党建相关的政策文件、规章制度等知识文档
    """

    __tablename__ = "knowledge_docs"

    # 文档标识（全局唯一）
    doc_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)

    # 文件名称
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # 文档标题
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    # 发文单位
    issuer: Mapped[str] = mapped_column(String(200), nullable=False)

    # 文号
    doc_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # 文档层级：central/provincial/school/department
    level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # 可见范围：public/school/department/branch
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # 保密级别：public/internal/sensitive/classified
    security_level: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # 生效日期
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # 失效日期（NULL 表示长期有效）
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    # 文件状态：effective/expired
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="effective", index=True)

    # 权威来源类别（T-DATA-05）：party_constitution/party_regulation/superior_document/
    # school_policy/reference；reference 为非权威参考资料，不能作为问答唯一依据。
    authority: Mapped[str] = mapped_column(
        String(30), nullable=False, default="reference", index=True
    )

    # 效力状态（T-DATA-05）：effective/pending/superseded/repealed；
    # 与按日期判定的 status 相互独立，两者在「已废止」处对齐。
    validity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="effective", index=True
    )

    # 公共库审核发布状态（T-KB-12）。默认 published 覆盖两类内容：
    # ① 非公共内容无需审核；② 迁移前的存量条目按已审核发布承接。
    # 公共可见内容经入库流程显式落为 pending，审核通过后才 published。
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="published", index=True
    )

    # 审核留痕：审核人（账号 id）、审核时间、审核意见
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 供给复核日程（T-KB-13）。责任部门、责任人与更新周期由学校「供给机制」按
    # 权威来源统一给出（见 app/services/governance_service.py 的 SupplyRule），
    # 条目上只落"最近一次复核/更新确认时间"与据此排定的"下次复核日期"。
    # 日程在入库、内容更新与复核确认时重排，不随机制变更回溯改写。
    maintained_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_review_at: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    # 字段级敏感等级（T-DATA-05）：{字段名: public/internal/sensitive/classified}。
    # 文档密级是该条目的上限，字段标注不得高于密级（入库与修元数据时校验），
    # 供下游脱敏与外发规则使用。
    field_levels: Mapped[Any | None] = mapped_column(JSON, nullable=True)

    # 主题标签（数组）
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)

    # 文档摘要
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 原始文件路径
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 文件大小（字节）
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 文档元数据（JSON）
    doc_metadata: Mapped[Any | None] = mapped_column("metadata", JSON, nullable=True)

    # 中文全文检索向量（生成列，随 title/summary 自动更新；配置见迁移 002）
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('chinese_zh', " "coalesce(title, '') || ' ' || coalesce(summary, ''))",
            persisted=True,
        ),
        nullable=True,
    )

    def __repr__(self) -> str:
        return f"<KnowledgeDoc(id={self.id}, title={self.title}, issuer={self.issuer})>"


class EmbeddingChunk(Base):
    """向量化片段表

    存储文档切分后的片段和向量
    """

    __tablename__ = "embedding_chunks"

    # 所属文档ID
    doc_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    # 片段ID（文档内唯一）
    chunk_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # 片段内容
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 片段在文档中的顺序
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    # 条款编号（如"第十四条"）
    article: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    # 向量嵌入（使用 pgvector）
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)

    # 片段元数据（继承文档元数据）
    chunk_metadata: Mapped[Any | None] = mapped_column("metadata", JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<EmbeddingChunk(id={self.id}, doc_id={self.doc_id}, chunk_id={self.chunk_id})>"
