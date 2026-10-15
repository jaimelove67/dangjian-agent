"""系统管理员创建账号的输入与输出契约。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.models.user import UserRole
from app.schemas.auth import UserInfo


class AccountCreateRequest(BaseModel):
    """租户从管理员登录态确定，禁止客户端指定租户或启用状态。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., min_length=1, max_length=50, pattern=r"^\S+$")
    name: str = Field(..., min_length=1, max_length=50)
    password: SecretStr = Field(..., min_length=8, max_length=72)
    role: UserRole
    org_unit_id: str = Field(..., min_length=1, max_length=36)

    @field_validator("username", "name", "org_unit_id", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        """剔除账号、姓名和组织编号两端空白，不修改密码。"""
        return value.strip() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        """拒绝空白密码和会被 bcrypt 截断的密码。"""
        password = value.get_secret_value()
        if not password.strip():
            raise ValueError("密码不能全部为空白")
        if len(password.encode("utf-8")) > 72:
            raise ValueError("密码的 UTF-8 编码不能超过 72 字节")
        return value


AccountOrgType = Literal["school", "department", "branch"]


class AccountOrgOption(BaseModel):
    """当前租户内可以分配给新账号的有效组织。"""

    id: str
    name: str
    org_type: AccountOrgType


class AccountCreated(UserInfo):
    """创建结果仅包含账号信息，不返回密码或密码哈希。"""

    org_name: str
