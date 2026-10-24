"""组织单元表模型"""

from datetime import date

from sqlalchemy import Boolean, Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrgUnit(Base):
    """组织单元表

    包括：学校、院系、支部等组织结构
    """

    __tablename__ = "org_units"
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # 组织名称
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # 组织类型：school/department/branch
    org_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # 父级组织ID
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # 组织层级路径
    path: Mapped[str] = mapped_column(String(500), nullable=False, index=True)

    # 主要负责人（现任快照）：姓名与职务分开存，换职务时不必改写姓名。
    # 完整任职履历在 OrgLeaderTerm，这里只留"当前主要负责人"便于列表直接展示。
    leader_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    leader_title: Mapped[str | None] = mapped_column(String(50), nullable=True)
    leader_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # 备注
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<OrgUnit(id={self.id}, name={self.name}, type={self.org_type})>"


class OrgLeaderTerm(Base):
    """组织负责人任职记录（历任）

    一个组织不同时期有不同负责人，同一时期也可能有多位（书记、副书记、委员），
    而 ``org_units`` 上只能放一位"当前主要负责人"，所以把任职事实单独成表：

    - 一条记录 = 一人在一个组织的一段任职；
    - ``ended_on`` 为空表示仍在任；离任只写日期，不删记录（履历要留痕）；
    - ``is_primary`` 标记是否主要负责人，变更后回写 ``org_units`` 的三个现任字段。

    注意：本表只记"谁在哪个组织任什么职务"，与党员组织关系接转
    （``member_transfers``）是两件事——干部任职不等于组织关系转移。
    """

    __tablename__ = "org_leader_terms"

    # 所属组织（不建外键：组织停用后履历仍需可查，与项目其它业务表一致）
    org_unit_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(50), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    started_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 为空 = 仍在任；离任只写日期，保留履历
    ended_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    # 是否该组织的主要负责人（书记）：是则同步到 org_units.leader_*
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    remark: Mapped[str | None] = mapped_column(String(200), nullable=True)

    def __repr__(self) -> str:
        return f"<OrgLeaderTerm(org={self.org_unit_id}, name={self.name}, title={self.title})>"
