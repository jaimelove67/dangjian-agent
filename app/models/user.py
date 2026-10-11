"""用户表模型"""

import enum

from sqlalchemy import Boolean
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserRole(str, enum.Enum):
    """用户角色"""

    SYSTEM_ADMIN = "system_admin"  # 系统管理员
    SCHOOL_ADMIN = "school_admin"  # 学校管理员
    DEPARTMENT_ADMIN = "department_admin"  # 院系管理员
    BRANCH_SECRETARY = "branch_secretary"  # 支部书记
    ORGANIZER = "organizer"  # 组织员
    MEMBER = "member"  # 普通党员
    APPLICANT = "applicant"  # 申请人


class User(Base):
    """用户表"""

    __tablename__ = "users"

    # 每次请求由身份校验重新计算，不落库、不接受客户端赋值。
    @property
    def knowledge_org_ids(self) -> list[str]:
        return list(
            self.__dict__.get("_knowledge_org_ids", [self.org_unit_id] if self.org_unit_id else [])
        )

    @knowledge_org_ids.setter
    def knowledge_org_ids(self, values: list[str]) -> None:
        self.__dict__["_knowledge_org_ids"] = list(values)

    # 用户名
    username: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)

    # 姓名
    name: Mapped[str] = mapped_column(String(50), nullable=False)

    # 密码哈希
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # 邮箱
    email: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True, index=True)

    # 手机号
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # 角色
    # 存储角色 *值*（如 branch_secretary）为 VARCHAR(50)，与迁移 001 的列定义保持一致，
    # 不创建原生 PG 枚举类型（避免 userrole 类型不存在 / 存储枚举名的问题）。
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(
            UserRole,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
            native_enum=False,
            length=50,
            create_constraint=False,
        ),
        nullable=False,
        default=UserRole.MEMBER,
    )

    # 所属组织ID
    org_unit_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    # 是否启用
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"
