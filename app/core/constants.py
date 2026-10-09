"""核心枚举常量

集中定义跨模块共享的取值，避免各模块自行定义导致不一致。

说明：``DataLevel`` 与 ``app.llm.base.DataLevel`` 取值保持一致（出网闸门使用后者），
此处独立定义是为了让 core 层（审计、权限）不依赖 ``app.llm`` 包。
"""
from enum import Enum


class DataLevel(str, Enum):
    """数据级别（决定是否允许使用外部模型）

    取值需与 ``app.llm.base.DataLevel`` 保持一致。
    """
    PUBLIC = "public"          # 公开数据
    INTERNAL = "internal"      # 内部数据
    SENSITIVE = "sensitive"    # 敏感数据，强制本地模型
    CLASSIFIED = "classified"  # 涉密数据，禁止 AI 处理


class AuditAction(str, Enum):
    """审计操作类型"""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    QUERY = "query"
    EXPORT = "export"
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    PERMISSION_DENIED = "permission_denied"
    MODEL_INVOKE = "model_invoke"
    STAGE_TRANSITION = "stage_transition"


class AuditResult(str, Enum):
    """审计结果"""
    SUCCESS = "success"
    FAILED = "failed"
    DENIED = "denied"


class DocumentLevel(str, Enum):
    """知识文档层级（见框架文档 5.2.1）"""
    CENTRAL = "central"          # 中央
    PROVINCIAL = "provincial"    # 省级
    SCHOOL = "school"            # 校级
    DEPARTMENT = "department"    # 院系级


class DocumentVisibility(str, Enum):
    """知识文档可见范围"""
    PUBLIC = "public"            # 公开
    SCHOOL = "school"            # 校级
    DEPARTMENT = "department"    # 院系级
    BRANCH = "branch"            # 支部级


class DocumentStatus(str, Enum):
    """知识文档状态（有效 / 已失效 / 已废止）"""
    EFFECTIVE = "effective"
    EXPIRED = "expired"
    ABOLISHED = "abolished"

