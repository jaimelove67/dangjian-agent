"""知识文档表模型"""
from datetime import datetime
from sqlalchemy import Column, String, Text, Date, JSON, Integer, Computed
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from pgvector.sqlalchemy import Vector

from app.db.base import Base


class KnowledgeDoc(Base):
    """知识文档表

    存储党建相关的政策文件、规章制度等知识文档
    """
    __tablename__ = "knowledge_docs"

    # 文档标识（全局唯一）
    doc_id = Column(String(100), nullable=False, unique=True, index=True)

    # 文件名称
    file_name = Column(String(255), nullable=False)

    # 文档标题
    title = Column(String(500), nullable=False)

    # 发文单位
    issuer = Column(String(200), nullable=False)

    # 文号
    doc_number = Column(String(100), nullable=True, index=True)

    # 文档层级：central/provincial/school/department
    level = Column(String(20), nullable=False, index=True)

    # 可见范围：public/school/department/branch
    visibility = Column(String(20), nullable=False, index=True)

    # 保密级别：public/internal/sensitive/classified
    security_level = Column(String(20), nullable=False, index=True)

    # 生效日期
    effective_date = Column(Date, nullable=False, index=True)

    # 失效日期（NULL 表示长期有效）
    expiration_date = Column(Date, nullable=True, index=True)

    # 文件状态：effective/expired
    status = Column(String(20), nullable=False, default="effective", index=True)

    # 主题标签（数组）
    tags = Column(ARRAY(String), nullable=True)

    # 文档摘要
    summary = Column(Text, nullable=True)

    # 原始文件路径
    file_path = Column(String(500), nullable=True)

    # 文件大小（字节）
    file_size = Column(Integer, nullable=True)

    # 文档元数据（JSON）
    doc_metadata = Column("metadata", JSON, nullable=True)

    # 中文全文检索向量（生成列，随 title/summary 自动更新；配置见迁移 002）
    search_vector = Column(
        TSVECTOR,
        Computed(
            "to_tsvector('chinese_zh', "
            "coalesce(title, '') || ' ' || coalesce(summary, ''))",
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
    doc_id = Column(String(36), nullable=False, index=True)

    # 片段ID（文档内唯一）
    chunk_id = Column(String(100), nullable=False, index=True)

    # 片段内容
    content = Column(Text, nullable=False)

    # 片段在文档中的顺序
    sequence = Column(Integer, nullable=False)

    # 条款编号（如"第十四条"）
    article = Column(String(50), nullable=True, index=True)

    # 向量嵌入（使用 pgvector）
    embedding = Column(Vector(1024), nullable=True)

    # 片段元数据（继承文档元数据）
    chunk_metadata = Column("metadata", JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<EmbeddingChunk(id={self.id}, doc_id={self.doc_id}, chunk_id={self.chunk_id})>"
