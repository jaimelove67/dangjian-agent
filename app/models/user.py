"""用户表模型"""
from sqlalchemy import Column, String, Enum as SQLEnum, Boolean
import enum

from app.db.base import Base


class UserRole(str, enum.Enum):
    """用户角色"""
    SYSTEM_ADMIN = "system_admin"           # 系统管理员
    SCHOOL_ADMIN = "school_admin"           # 学校管理员
    DEPARTMENT_ADMIN = "department_admin"   # 院系管理员
    BRANCH_SECRETARY = "branch_secretary"   # 支部书记
    ORGANIZER = "organizer"                 # 组织员
    MEMBER = "member"                       # 普通党员
    APPLICANT = "applicant"                 # 申请人


class User(Base):
    """用户表"""
    __tablename__ = "users"

    # 用户名
    username = Column(String(50), nullable=False, unique=True, index=True)

    # 姓名
    name = Column(String(50), nullable=False)

    # 密码哈希
    password_hash = Column(String(255), nullable=False)

    # 邮箱
    email = Column(String(100), nullable=True, unique=True, index=True)

    # 手机号
    phone = Column(String(20), nullable=True)

    # 角色
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.MEMBER)

    # 所属组织ID
    org_unit_id = Column(String(36), nullable=True, index=True)

    # 是否启用
    is_active = Column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"
