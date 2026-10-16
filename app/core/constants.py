"""核心枚举常量

集中定义跨模块共享的取值，避免各模块自行定义导致不一致。

说明：``DataLevel`` 与 ``app.llm.base.DataLevel`` 取值保持一致（出网闸门使用后者），
此处独立定义是为了让 core 层（审计、权限）不依赖 ``app.llm`` 包。
"""

from datetime import date
from enum import Enum


class DataLevel(str, Enum):
    """数据级别（决定是否允许使用外部模型）

    取值需与 ``app.llm.base.DataLevel`` 保持一致。
    """

    PUBLIC = "public"  # 公开数据
    INTERNAL = "internal"  # 内部数据
    SENSITIVE = "sensitive"  # 敏感数据，强制本地模型
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
    REVIEW = "review"
    MAINTAIN = "maintain"


class AuditResult(str, Enum):
    """审计结果"""

    SUCCESS = "success"
    FAILED = "failed"
    DENIED = "denied"


class DocumentLevel(str, Enum):
    """知识文档层级（见框架文档 5.2.1）"""

    CENTRAL = "central"  # 中央
    PROVINCIAL = "provincial"  # 省级
    SCHOOL = "school"  # 校级
    DEPARTMENT = "department"  # 院系级


class DocumentVisibility(str, Enum):
    """知识文档可见范围"""

    PUBLIC = "public"  # 公开
    SCHOOL = "school"  # 校级
    DEPARTMENT = "department"  # 院系级
    BRANCH = "branch"  # 支部级


class DocumentStatus(str, Enum):
    """知识文档状态（有效 / 已失效 / 已废止）

    这是按``生效日期 / 失效日期``自动判定的运行状态；与人工维护的
    :class:`DocumentValidity`（效力状态）相互独立，两者在``废止``处对齐。
    """

    EFFECTIVE = "effective"
    EXPIRED = "expired"
    ABOLISHED = "abolished"


class DocumentAuthority(str, Enum):
    """知识条目权威来源类别（FR-KB-04 / FR-KB-10）

    ``reference``（参考资料）是非权威来源：可以入库和检索，但不能作为问答的
    唯一依据输出（见 :func:`is_authoritative`）。
    """

    PARTY_CONSTITUTION = "party_constitution"  # 党章
    PARTY_REGULATION = "party_regulation"  # 党内法规
    SUPERIOR_DOCUMENT = "superior_document"  # 上级文件
    SCHOOL_POLICY = "school_policy"  # 学校 / 院系制度
    REFERENCE = "reference"  # 参考资料（非权威）


class DocumentValidity(str, Enum):
    """知识条目效力状态（FR-KB-04）

    现行有效 / 尚未生效 / 已被新版替代 / 已废止；由维护人员人工确认，用于
    判定条目能否作为权威依据（见 :func:`is_in_force`）。
    """

    EFFECTIVE = "effective"  # 现行有效
    PENDING = "pending"  # 尚未生效
    SUPERSEDED = "superseded"  # 已被新版替代
    REPEALED = "repealed"  # 已废止


class DocumentReviewStatus(str, Enum):
    """公共库内容的审核发布状态（T-KB-12）

    公共可见内容入库后为``pending``，经审核人批准才``published``（可被检索）；
    非公共内容不需要审核，直接``published``。``rejected``表示已退回待修正。
    """

    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"


# 供给机制的更新周期边界（T-KB-13）：下限一个月，避免"每周复核"退化成空转；
# 上限十年，避免机制被写成"基本不复核"。
REVIEW_CYCLE_MIN_DAYS = 30
REVIEW_CYCLE_MAX_DAYS = 3650

# Excel 导出/模板的 MIME（名册与问答记录等台账导出共用，避免各写一份）
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# 字段级敏感等级允许标注的文档元数据字段（T-DATA-05）
SENSITIVE_FIELD_KEYS: tuple[str, ...] = (
    "title",
    "issuer",
    "doc_number",
    "summary",
    "file_name",
    "tags",
)


def is_authoritative(authority: str | None) -> bool:
    """是否为权威来源

    只有显式标注``reference``才算非权威。历史数据或未标注来源的调用方按权威
    处理，与迁移回填口径一致——不能因为缺少字段就把存量制度整体降级。
    """
    return authority != DocumentAuthority.REFERENCE.value


def is_in_force(validity: str | None) -> bool:
    """是否现行有效

    只有显式标注``pending/superseded/repealed``才算非现行效力；未标注按现行
    有效处理，与迁移回填口径一致。
    """
    return validity in (None, "", DocumentValidity.EFFECTIVE.value)


def is_review_due(
    next_review_at: date | None,
    *,
    status: str | None,
    validity: str | None,
    today: date | None = None,
) -> bool:
    """是否已到复核期限（T-KB-13）

    这是内容维护信号，**不**参与检索依据判定：到期意味着"该找责任人核对了"，
    而不是"不能用了"。只有现行有效的条目才谈得上到期——已废止、已失效或尚未
    生效的条目没有复核义务。
    """
    if next_review_at is None:
        return False
    if status not in (None, DocumentStatus.EFFECTIVE.value):
        return False
    if not is_in_force(validity):
        return False
    return next_review_at <= (today or date.today())
