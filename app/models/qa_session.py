"""长期问答记录，与 Redis 中有期限的多轮上下文分别保存。"""

from sqlalchemy import JSON, Boolean, Column, Index, Integer, String, Text

from app.db.base import Base
from app.schemas.qa import DEFAULT_DISCLAIMER


class QASession(Base):
    __tablename__ = "qa_sessions"
    __table_args__ = (Index("ix_qa_sessions_user_created", "tenant_id", "user_id", "created_at"),)

    user_id = Column(String(36), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    citations = Column(JSON, nullable=False, default=list)
    data_level = Column(String(20), nullable=False, default="public")
    has_sufficient_evidence = Column(Boolean, nullable=False, default=False)
    retrieved_count = Column(Integer, nullable=False, default=0)
    used_count = Column(Integer, nullable=False, default=0)
    warnings = Column(JSON, nullable=False, default=list)
    disclaimer = Column(Text, nullable=False, default=DEFAULT_DISCLAIMER)
    refused = Column(Boolean, nullable=False, default=False)
    session_id = Column(String(64), nullable=True)
