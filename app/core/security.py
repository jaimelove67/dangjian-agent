"""安全与权限模块

提供：

- 密码哈希与校验（bcrypt）
- JWT 令牌签发与校验（python-jose）
- 角色与数据范围模型（"角色 + 数据范围"双层，见框架文档 9.1）
- 接口权限矩阵与判定（见开发规范 8.3）

设计约定：本模块只承载**纯逻辑**（密码 / 令牌 / 权限判定），不依赖 FastAPI 与
数据库，便于单元测试。FastAPI 依赖注入见 ``app/deps.py``。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, cast

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings
from app.core.constants import DataLevel
from app.models.user import UserRole


# ==================== 异常 ====================
class SecurityError(Exception):
    """安全相关异常基类"""


class TokenError(SecurityError):
    """令牌缺失、无效或已过期"""


class PermissionDenied(SecurityError):
    """权限不足"""


class AuthenticationError(SecurityError):
    """认证失败（用户名或密码错误等）"""


# ==================== 密码哈希 ====================
# bcrypt 仅使用前 72 字节，超出部分需显式截断，否则新版本库会报错
_BCRYPT_MAX_BYTES = 72


def _to_bcrypt_bytes(password: str) -> bytes:
    """将明文密码编码为 bcrypt 可处理的字节串"""
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str, rounds: int | None = None) -> str:
    """生成密码哈希

    Args:
        password: 明文密码
        rounds: bcrypt 成本因子，默认取配置 BCRYPT_ROUNDS

    Returns:
        bcrypt 哈希字符串
    """
    if not password:
        raise ValueError("密码不能为空")
    salt = bcrypt.gensalt(rounds=rounds or settings.BCRYPT_ROUNDS)
    return bcrypt.hashpw(_to_bcrypt_bytes(password), salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """校验密码

    Args:
        plain_password: 明文密码
        password_hash: 已存储的哈希

    Returns:
        是否匹配
    """
    if not plain_password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(_to_bcrypt_bytes(plain_password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ==================== JWT 令牌 ====================
class TokenType(str, Enum):
    """令牌类型"""

    ACCESS = "access"
    REFRESH = "refresh"


def _encode(subject: str, token_type: TokenType, expires: timedelta, **claims: Any) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type.value,
        "iat": int(now.timestamp()),
        "exp": int((now + expires).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    for key, value in claims.items():
        if value is None:
            continue
        payload[key] = value.value if isinstance(value, Enum) else value
    return cast(str, jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM))


def create_access_token(
    subject: str,
    tenant_id: str | None = None,
    role: UserRole | None = None,
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """签发访问令牌

    Args:
        subject: 主体（通常为用户 ID）
        tenant_id: 租户 ID（从登录态解析，不接受前端传入）
        role: 用户角色
        expires_minutes: 有效期（分钟），默认取配置
        extra_claims: 额外声明

    Returns:
        JWT 字符串
    """
    minutes = expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    claims: dict[str, Any] = {"tenant_id": tenant_id, "role": role}
    if extra_claims:
        claims.update(extra_claims)
    return _encode(subject, TokenType.ACCESS, timedelta(minutes=minutes), **claims)


def create_refresh_token(
    subject: str,
    tenant_id: str | None = None,
    role: UserRole | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """签发刷新令牌"""
    return _encode(
        subject,
        TokenType.REFRESH,
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        tenant_id=tenant_id,
        role=role,
        **(extra_claims or {}),
    )


def decode_token(token: str, expected_type: TokenType | None = None) -> dict[str, Any]:
    """解码并校验令牌

    Args:
        token: JWT 字符串
        expected_type: 期望的令牌类型，校验不通过则报错

    Returns:
        令牌载荷

    Raises:
        TokenError: 令牌无效、过期或类型不符
    """
    if not token:
        raise TokenError("令牌缺失")
    try:
        payload = cast(
            "dict[str, Any]",
            jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]),
        )
    except JWTError as exc:
        raise TokenError(f"令牌无效或已过期: {exc}") from exc

    if expected_type is not None and payload.get("type") != expected_type.value:
        raise TokenError(f"令牌类型不符，期望 {expected_type.value}")
    return payload


# ==================== 角色与数据范围 ====================
class Permission(str, Enum):
    """接口权限点（对应开发规范 8.3 接口权限要求）"""

    QA_ASK = "qa.ask"  # 知识问答：登录用户
    KNOWLEDGE_QUERY = "knowledge.query"  # 知识检索：登录用户
    KNOWLEDGE_MANAGE = "knowledge.manage"  # 知识库维护：院系级及以上管理员
    MEMBER_QUERY = "member.query"  # 党员发展查询：支部书记及以上
    STAGE_TRANSITION = "member.stage_transition"  # 阶段流转：支部书记及以上
    SCORING = "member.scoring"  # 辅助评分：支部书记及以上
    MEETING_QUERY = "meeting.query"  # 组织生活查询：支部书记及以上
    MEETING_MANAGE = "meeting.manage"  # 组织生活登记与纪要维护：支部书记及以上
    MEETING_REVIEW = "meeting.review"  # 组织生活纪要审核：支部书记及以上
    MEETING_ARCHIVE = "meeting.archive"  # 会议归档：支部书记及以上
    ASSESSMENT_QUERY = "assessment.query"
    ASSESSMENT_MANAGE = "assessment.manage"
    ASSESSMENT_CONFIGURE = "assessment.configure"
    ASSESSMENT_REVIEW = "assessment.review"
    ASSESSMENT_EXPORT = "assessment.export"
    STUDY_QUERY = "study.query"
    STUDY_MANAGE = "study.manage"
    STUDY_REVIEW = "study.review"
    ARCHIVE_CONFIRM = "admin.archive_confirm"
    CONFIG_MANAGE = "admin.config"  # 配置管理：系统管理员
    AUDIT_QUERY = "admin.audit"  # 审计查询：系统管理员


@dataclass(frozen=True)
class RoleProfile:
    """角色画像：知识库可见范围 + 业务数据范围 + 权限点 + 数据级别上限"""

    role: UserRole
    knowledge_scopes: frozenset[str]
    business_scope: str
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    data_level: DataLevel = DataLevel.INTERNAL


# 知识库可见范围取值
KS_PUBLIC = "public"
KS_SCHOOL = "school"
KS_DEPARTMENT = "department"
KS_BRANCH = "branch"

# 业务数据范围取值（层级由小到大：self < branch < department < school < all）
BS_SELF = "self"
BS_BRANCH = "branch"
BS_DEPARTMENT = "department"
BS_SCHOOL = "school"
BS_ALL = "all"

_BUSINESS_SCOPE_ORDER = {BS_SELF: 0, BS_BRANCH: 1, BS_DEPARTMENT: 2, BS_SCHOOL: 3, BS_ALL: 4}

# 合并权限集合，便于复用
_ALL_PERMISSIONS = frozenset(Permission)
_MANAGER_PERMISSIONS = frozenset(
    {
        Permission.QA_ASK,
        Permission.KNOWLEDGE_QUERY,
        Permission.KNOWLEDGE_MANAGE,
        Permission.MEMBER_QUERY,
        Permission.STAGE_TRANSITION,
        Permission.SCORING,
        Permission.MEETING_QUERY,
        Permission.MEETING_MANAGE,
        Permission.MEETING_REVIEW,
        Permission.MEETING_ARCHIVE,
        Permission.STUDY_QUERY,
        Permission.STUDY_MANAGE,
        Permission.STUDY_REVIEW,
        Permission.ASSESSMENT_QUERY,
        Permission.ASSESSMENT_MANAGE,
        Permission.ASSESSMENT_REVIEW,
        Permission.ASSESSMENT_EXPORT,
    }
)
_BRANCH_PERMISSIONS = frozenset(
    {
        Permission.QA_ASK,
        Permission.KNOWLEDGE_QUERY,
        Permission.MEMBER_QUERY,
        Permission.STAGE_TRANSITION,
        Permission.SCORING,
        Permission.MEETING_QUERY,
        Permission.MEETING_MANAGE,
        Permission.MEETING_REVIEW,
        Permission.MEETING_ARCHIVE,
        Permission.ASSESSMENT_QUERY,
        Permission.ASSESSMENT_MANAGE,
        Permission.ASSESSMENT_EXPORT,
    }
)
_MEMBER_PERMISSIONS = frozenset({Permission.QA_ASK, Permission.KNOWLEDGE_QUERY})

# 角色画像（对应框架文档 9.1 角色与数据范围表）
ROLE_PROFILES: dict[UserRole, RoleProfile] = {
    UserRole.SYSTEM_ADMIN: RoleProfile(
        role=UserRole.SYSTEM_ADMIN,
        knowledge_scopes=frozenset({KS_PUBLIC, KS_SCHOOL, KS_DEPARTMENT, KS_BRANCH}),
        business_scope=BS_ALL,
        permissions=_ALL_PERMISSIONS,
        data_level=DataLevel.SENSITIVE,
    ),
    UserRole.SCHOOL_ADMIN: RoleProfile(
        role=UserRole.SCHOOL_ADMIN,
        knowledge_scopes=frozenset({KS_PUBLIC, KS_SCHOOL}),
        business_scope=BS_SCHOOL,
        permissions=_MANAGER_PERMISSIONS
        | frozenset({Permission.ARCHIVE_CONFIRM, Permission.ASSESSMENT_CONFIGURE}),
        data_level=DataLevel.SENSITIVE,
    ),
    UserRole.DEPARTMENT_ADMIN: RoleProfile(
        role=UserRole.DEPARTMENT_ADMIN,
        knowledge_scopes=frozenset({KS_PUBLIC, KS_SCHOOL, KS_DEPARTMENT}),
        business_scope=BS_DEPARTMENT,
        permissions=_MANAGER_PERMISSIONS,
        data_level=DataLevel.SENSITIVE,
    ),
    UserRole.BRANCH_SECRETARY: RoleProfile(
        role=UserRole.BRANCH_SECRETARY,
        knowledge_scopes=frozenset({KS_PUBLIC, KS_SCHOOL, KS_DEPARTMENT, KS_BRANCH}),
        business_scope=BS_BRANCH,
        permissions=_BRANCH_PERMISSIONS | frozenset({Permission.ASSESSMENT_REVIEW}),
        data_level=DataLevel.SENSITIVE,
    ),
    UserRole.ORGANIZER: RoleProfile(
        role=UserRole.ORGANIZER,
        knowledge_scopes=frozenset({KS_PUBLIC, KS_SCHOOL, KS_DEPARTMENT, KS_BRANCH}),
        business_scope=BS_BRANCH,
        permissions=_BRANCH_PERMISSIONS,
        data_level=DataLevel.SENSITIVE,
    ),
    UserRole.MEMBER: RoleProfile(
        role=UserRole.MEMBER,
        knowledge_scopes=frozenset({KS_PUBLIC, KS_SCHOOL}),
        business_scope=BS_SELF,
        permissions=_MEMBER_PERMISSIONS,
        data_level=DataLevel.INTERNAL,
    ),
    UserRole.APPLICANT: RoleProfile(
        role=UserRole.APPLICANT,
        knowledge_scopes=frozenset({KS_PUBLIC}),
        business_scope=BS_SELF,
        permissions=_MEMBER_PERMISSIONS,
        data_level=DataLevel.PUBLIC,
    ),
}


def get_role_profile(role: UserRole) -> RoleProfile:
    """获取角色画像；未知角色按最小权限（申请人）处理"""
    return ROLE_PROFILES.get(role, ROLE_PROFILES[UserRole.APPLICANT])


def has_permission(role: UserRole, permission: Permission) -> bool:
    """判断角色是否具备某权限点"""
    return permission in get_role_profile(role).permissions


def resolve_data_level(role: UserRole) -> DataLevel:
    """由角色推导用户的数据级别上限（不接受前端传入）"""
    return get_role_profile(role).data_level


def can_access_knowledge_scope(role: UserRole, scope: str) -> bool:
    """判断角色的知识库可见范围是否覆盖指定范围"""
    return scope in get_role_profile(role).knowledge_scopes


def can_access_business_scope(role: UserRole, required_scope: str) -> bool:
    """判断角色业务数据范围是否覆盖所需范围（按层级比较）"""
    profile = get_role_profile(role)
    user_rank = _BUSINESS_SCOPE_ORDER.get(profile.business_scope, -1)
    required_rank = _BUSINESS_SCOPE_ORDER.get(required_scope, 99)
    return user_rank >= required_rank
